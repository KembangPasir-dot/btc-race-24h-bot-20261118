import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
from makefun_bars import run

SYMBOL = "CBBTC"
LEVELS = (990, 980, 975)
TP = 1010
MAX_TRIPS = 2
TIME_EXIT = 0
DIP = 992
start = None
closes = []
tranches = []
pending = {}
serial = 0
blocked = False


def on_batch(state, batch):
    global start, serial, blocked
    bar = next((b for b in batch["bars"] if b["symbol"] == SYMBOL), None)
    if bar is None or state.warming_up:
        return []
    close = int(bar["c"])
    seq = batch["seq"] - state.warmup_bars
    if start is None:
        start = close
        capital = int(state.hello["capital"]["quote_units"])
        for i, level in enumerate(LEVELS):
            budget = capital // len(LEVELS) + (capital % len(LEVELS) if i == 0 else 0)
            tranches.append(dict(level=level, cash=budget, qty=0, entry=0, since=0, trips=0))
    closes.append(close)
    for fill in batch["fills"]:
        record = pending.pop(fill.get("client_id"), None)
        if record is None:
            continue
        i, side = record
        t = tranches[i]
        if fill["status"] != "filled":
            if fill.get("reason") == "max_open_positions":
                blocked = True
            continue
        if side == "buy":
            t.update(qty=int(fill["qty"]), entry=int(fill["price"]), since=seq)
            t["cash"] -= int(fill["notional_quote_units"])
        else:
            t["cash"] += int(fill["notional_quote_units"]) - int(fill["fee_quote_units"])
            t["qty"] = 0
            t["trips"] += 1
    if SYMBOL not in state.positions:
        blocked = False
    orders = []
    remaining = state.cash
    dip = len(closes) >= 15 and close * 1000 <= closes[-15] * DIP and close > closes[-2]
    dip_used = False
    for i, t in enumerate(tranches):
        side = None
        if t["qty"]:
            if (close * 1000 >= t["entry"] * TP or close * 1000 < t["entry"] * 975
                    or (TIME_EXIT and seq - t["since"] >= TIME_EXIT)):
                side = "sell"
                order = dict(side=side, symbol=SYMBOL, qty=t["qty"], max_slippage_bps=100)
        elif t["trips"] < MAX_TRIPS and not blocked:
            signal = close * 1000 <= start * t["level"] or (dip and not dip_used) or seq >= 720
            amount = min(t["cash"], remaining, state.weight_room(SYMBOL))
            if signal and amount >= int(state.hello["fees"]["min_notional_quote_units"]):
                side = "buy"
                dip_used = True
                remaining -= amount
                order = dict(side=side, symbol=SYMBOL, notional_quote_units=amount, max_slippage_bps=100)
        if side:
            serial += 1
            cid = "tranche-" + str(serial)
            order["client_id"] = cid
            pending[cid] = (i, side)
            orders.append(order)
    return orders


run(on_batch)
