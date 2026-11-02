"""Preview or apply the Zheshang US-equity fee correction, preserving other fields."""
import argparse
import datetime as dt
import json
from pathlib import Path
import tomllib
import urllib.request

import app as core


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config = tomllib.loads((root / ".streamlit/secrets.toml").read_text(encoding="utf-8"))["apps_script"]

    def call(action, **payload):
        body = json.dumps({"token": config["token"], "action": action, **payload}).encode("utf-8")
        req = urllib.request.Request(config["url"], data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Apps Script error"))
        return result

    cloud = call("read_trades")["rows"]
    local_path = root / "data/streamlit_trades.json"
    local = json.loads(local_path.read_text(encoding="utf-8")) if local_path.exists() else []
    changes = []
    for location, rows in [("cloud", cloud), ("local", local)]:
        for row in rows:
            symbol = row.get("fmp_symbol") or row.get("symbol") or ""
            if row.get("broker") != "浙商" or str(row.get("currency", "")).upper() != "USD" or core.is_hk_symbol(symbol):
                continue
            fee = core.calculated_fee(symbol, float(row["quantity"]), float(row["price"]), "USD",
                                      broker="浙商", side=row["side"], trade_date=row["date"])
            old = float(row.get("fee") or 0)
            if abs(old - fee) > 0.000001:
                changes.append((location, row, old, fee))
    print(json.dumps({"mode": "apply" if args.apply else "preview", "changes": len(changes),
                      "cloud_changes": sum(x[0] == "cloud" for x in changes),
                      "fee_reduction_usd": round(sum(x[2] - x[3] for x in changes if x[0] == "cloud"), 2),
                      "items": [{"location": loc, "id": row["id"], "date": row["date"],
                                 "symbol": row["symbol"], "old_fee": old, "new_fee": fee}
                                for loc, row, old, fee in changes]}, ensure_ascii=False))
    if not args.apply or not changes:
        return
    backup = root / "data" / ("fee_backup_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps({"cloud": cloud, "local": local}, ensure_ascii=False, indent=2), encoding="utf-8")
    for location, row, old, fee in changes:
        updated = {**row, "fee": fee}
        if location == "cloud":
            call("update_trade", trade=updated, audit={
                "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(), "user": "fee_migration",
                "action": "RECALCULATE_FEE", "symbol": row["symbol"], "side": row["side"],
                "quantity": row["quantity"], "price": row["price"],
                "note": f"Zheshang US fee: {old} -> {fee}; commission 0.008/share, min 2; dated SEC/TAF",
            })
        else:
            row["fee"] = fee
    if any(x[0] == "local" for x in changes):
        local_path.write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
    actual = {row["id"]: row for row in call("read_trades")["rows"]}
    expected_fees = {row["id"]: fee for location, row, old, fee in changes if location == "cloud"}
    assert len(actual) == len(cloud), "Cloud row count changed"
    for original in cloud:
        expected = {**original}
        if original["id"] in expected_fees:
            expected["fee"] = expected_fees[original["id"]]
        assert actual[original["id"]] == expected, original["id"]
    for location, row, old, fee in changes:
        if location == "cloud":
            assert abs(float(actual[row["id"]]["fee"]) - fee) < 0.000001, row["id"]
            assert all(actual[row["id"]].get(key) == value for key, value in row.items() if key != "fee"), row["id"]
    print("Applied and verified. Backup: " + str(backup))


if __name__ == "__main__":
    main()
