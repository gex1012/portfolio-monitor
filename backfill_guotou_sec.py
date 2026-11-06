"""Backfill missing Guotou sell-side SEC fees; never reduce existing actual fees."""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
import tomllib
import urllib.request

import app as core


def plan(rows):
    changes, review = [], []
    for row in rows:
        symbol = core.fmp_symbol(row.get("fmp_symbol") or row.get("symbol") or "")
        if (row.get("broker") or "国投") != "国投" or str(row.get("currency", "")).upper() != "USD":
            continue
        if core.is_hk_symbol(symbol) or str(row.get("side", "")).upper() != "SELL":
            continue
        if not row.get("date"):
            review.append({"id": row["id"], "reason": "missing trade date"})
            continue
        fees = core.guotou_us_fee(float(row["quantity"]), float(row["price"]), "SELL", row["date"])
        old = float(row.get("fee") or 0)
        if not fees["sec"] or old >= fees["total"] - 1e-6:
            continue
        # Only demonstrably commission-only records can be topped up safely.
        if not math.isclose(old, fees["commission"], abs_tol=1e-6) and not math.isclose(old, round(fees["commission"], 2), abs_tol=1e-6):
            review.append({"id": row["id"], "symbol": symbol, "old_fee": old,
                           "commission": fees["commission"], "sec": fees["sec"], "reason": "custom fee needs reconciliation"})
            continue
        changes.append({"id": row["id"], "symbol": symbol, "date": row["date"],
                        "old_fee": old, "new_fee": float(core.Decimal(str(old)) + core.Decimal(str(fees["sec"]))),
                        "sec": fees["sec"]})
    return changes, review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config = tomllib.loads((root / ".streamlit/secrets.toml").read_text(encoding="utf-8"))["apps_script"]

    def call(action, **payload):
        request = urllib.request.Request(config["url"],
            data=json.dumps({"token": config["token"], "action": action, **payload}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Apps Script error"))
        return result

    cloud = call("read_trades")["rows"]
    local_path = root / "data/streamlit_trades.json"
    local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.exists() else []
    changes, review = plan(cloud)
    local_changes, local_review = plan(local)
    print(json.dumps({"mode": "apply" if args.apply else "preview", "cloud_changes": len(changes),
        "added_fee_usd": round(sum(item["sec"] for item in changes), 2), "items": changes,
        "needs_review": review, "local_changes": local_changes, "local_review": local_review}, ensure_ascii=False), flush=True)
    if not args.apply or not (changes or local_changes):
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = root / "data" / f"guotou_sec_backup_{stamp}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps({"cloud": cloud, "local": local, "changes": changes}, ensure_ascii=False, indent=2), encoding="utf-8")
    assert call("read_trades")["rows"] == cloud, "Ledger changed since preview; rerun before applying"
    originals = {row["id"]: row for row in cloud}
    assert len(originals) == len(cloud), "Duplicate trade IDs"
    expected = dict(originals)
    for change in changes:
        row = originals[change["id"]]
        updated = {**row, "fee": change["new_fee"]}
        call("update_trade", trade=updated, audit={"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "user": "fee_migration", "action": "BACKFILL_SEC_FEE", "symbol": row["symbol"],
            "side": row["side"], "quantity": row["quantity"], "price": row["price"],
            "note": f"Guotou sell SEC +{change['sec']}; fee {change['old_fee']} -> {change['new_fee']}; original commission preserved"})
        expected[row["id"]] = updated
        print("Updated " + row["id"], flush=True)
    local_updates = {item["id"]: item["new_fee"] for item in local_changes}
    for row in local:
        if row["id"] in local_updates:
            row["fee"] = local_updates[row["id"]]
    if local_changes:
        local_path.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
    actual = call("read_trades")["rows"]
    assert len(actual) == len(cloud) and {row["id"]: row for row in actual} == expected, "Ledger verification failed"
    assert not plan(actual)[0], "Backfill is not idempotent"
    print("Applied and verified all fields; rerun adds no duplicate fees. Backup: " + str(backup), flush=True)


if __name__ == "__main__":
    main()
