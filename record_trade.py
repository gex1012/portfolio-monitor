from __future__ import annotations

import argparse

from app import load_ledger, normalize_trade, save_ledger


def main() -> None:
    parser = argparse.ArgumentParser(description="Append one manual trade to the portfolio ledger.")
    parser.add_argument("side", choices=["BUY", "SELL"])
    parser.add_argument("symbol")
    parser.add_argument("quantity", type=float)
    parser.add_argument("price", type=float)
    parser.add_argument("--currency", default="")
    parser.add_argument("--fee", type=float, default=0.0)
    parser.add_argument("--date", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    trade = normalize_trade(vars(args))
    rows = load_ledger()
    rows.append(trade)
    save_ledger(rows)
    print(f"saved {trade['side']} {trade['quantity']} {trade['symbol']} @ {trade['price']} {trade['currency']}")


if __name__ == "__main__":
    main()

