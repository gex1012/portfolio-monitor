"""Split events are replayed alongside trades, never written as fake buys."""
from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo


def trade_day(value):
    if not value:
        return ""
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    # Sheets serializes a trading-date cell at midnight in Hong Kong.
    if parsed.tzinfo:
        parsed = parsed.astimezone(ZoneInfo("Asia/Hong_Kong"))
    return parsed.date().isoformat()


def normalize_splits(symbol, rows, source):
    events = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            date = dt.date.fromisoformat(str(row["date"])[:10]).isoformat()
            numerator, denominator = float(row["numerator"]), float(row["denominator"])
            ratio = numerator / denominator
            if not all(math.isfinite(x) and x > 0 for x in (numerator, denominator, ratio)) or ratio == 1:
                continue
        except (KeyError, ValueError, TypeError, ZeroDivisionError, OverflowError):
            continue
        event = {"id": f"split:{symbol}:{date}", "symbol": symbol, "date": date,
                 "numerator": numerator, "denominator": denominator, "ratio": ratio,
                 "source": source, "event_type": "split"}
        if date in events and not math.isclose(events[date]["ratio"], ratio):
            raise ValueError(f"Conflicting split ratios: {symbol} {date}")
        events[date] = event
    return list(events.values())


def is_effective(event, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if isinstance(now, dt.datetime):
        zone = "Asia/Hong_Kong" if event["symbol"].endswith((".HK", ".SS", ".SZ")) else "America/New_York"
        opening = dt.datetime.combine(dt.date.fromisoformat(event["date"]), dt.time(9, 30), ZoneInfo(zone))
        return now >= opening
    return event["date"] <= now.isoformat()


def portfolio_timeline(trades, events, now=None):
    active = {event["id"]: event for event in events if is_effective(event, now)}
    # Undated opening imports are a snapshot, not holdings since the company's
    # inception. Anchor at ledger start to avoid applying decades-old splits.
    anchor = min((trade_day(t["date"]) for t in trades if t.get("date")),
                 default=(now.date() if isinstance(now, dt.datetime) else now or dt.date.today()).isoformat())
    return sorted([*trades, *active.values()], key=lambda item: (
        item["date"] if item.get("event_type") == "split" else trade_day(item.get("date")) or anchor,
        0 if item.get("event_type") == "split" else (-1 if not item.get("date") else 1), item.get("id", "")))


def apply_split(positions, event):
    applied = []
    for pos in positions.values():
        if pos["symbol"] != event["symbol"] or abs(pos["quantity"]) < 1e-9:
            continue
        before = pos["quantity"]
        pos["quantity"] *= event["ratio"]
        applied.append({**event, "broker": pos.get("broker", ""), "before": before,
                        "after": pos["quantity"], "cost": pos["cost"],
                        "fractional": not math.isclose(pos["quantity"], round(pos["quantity"]), abs_tol=1e-8)})
    return applied


def adjust_raw_history(rows, events, now=None):
    """Only for explicitly UNADJUSTED OHLC, not FMP full or Yahoo charts."""
    result = []
    for row in rows:
        factor = math.prod(e["ratio"] for e in events
                           if is_effective(e, now) and row["date"] < e["date"])
        result.append({**row, **{field: row.get(field, 0) / factor for field in ("open", "high", "low", "close")},
                       "volume": row.get("volume", 0) * factor})
    return result


class SplitQuotePending(RuntimeError):
    pass


def validate_split_quotes(adjustments, quotes):
    for event in adjustments:
        quote = quotes.get(event["symbol"], {})
        timestamp = quote.get("timestamp")
        if not timestamp:
            continue
        try:
            when = dt.datetime.fromtimestamp(float(timestamp), dt.timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if not is_effective(event, when):
            raise SplitQuotePending(f"{event['symbol']}: quote predates the {event['date']} split. "
                                    "Valuation paused until a post-split quote is available. Refresh data to retry.")
