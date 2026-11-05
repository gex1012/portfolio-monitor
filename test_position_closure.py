import datetime as dt
import unittest
from unittest.mock import patch

import streamlit_app as monitor


class PositionClosureTests(unittest.TestCase):
    def calculate(self, rows):
        with patch.object(monitor.core, "quote_for_symbols", return_value={"MRVL": {"price": 157}}), \
             patch.object(monitor.core, "stock_split_events", return_value={"events": [], "warnings": []}), \
             patch.object(monitor.core, "fx_rates_to_usd", return_value={"to_usd": {"USD": 1, "HKD": 1 / 7.8}}), \
             patch.object(monitor.core, "period_return", return_value=None), \
             patch.object(monitor, "period_return_ytd", return_value=None), \
             patch.object(monitor, "load_dividend_records", return_value=[]):
            return monitor.compute_portfolio_from_trades(rows)

    def opening(self):
        return {"id": "excel-36-buy", "date": "", "source": "initial_excel", "symbol": "MRVL",
                "side": "BUY", "quantity": 100, "price": 301, "fee": 60.2, "currency": "USD"}

    def sale(self, qty=100):
        return {"id": "sale", "date": "2026-11-04", "symbol": "mrvl", "side": "SELL",
                "quantity": qty, "price": 157, "fee": 31.4, "currency": "USD", "broker": "国投"}

    def test_undated_initial_buy_is_not_recreated_after_sale(self):
        result = self.calculate([self.sale(), self.opening()])
        self.assertEqual(result["holdings"], [])
        self.assertEqual(result["projects"][0]["status"], "closed")
        self.assertAlmostEqual(result["account"]["realized_pnl_usd"], -14491.6)
        self.assertAlmostEqual(result["account"]["unrealized_pnl_usd"], 0)
        self.assertEqual(result["transactions"][0]["date"], "")

    def test_partial_sale_retains_only_remaining_shares(self):
        result = self.calculate([self.sale(60), self.opening()])
        self.assertEqual(result["holdings"][0]["quantity"], 40)
        self.assertAlmostEqual(result["holdings"][0]["avg_cost"], 301.602)

    def test_closure_is_independent_for_each_broker(self):
        rows = [self.opening(), self.sale(),
                {"id": "zs-buy", "date": "2026-08-04", "symbol": "MRVL", "side": "BUY",
                 "broker": "浙商", "quantity": 100, "price": 218, "fee": 2},
                {"id": "zs-sell-1", "date": "2026-08-19", "symbol": "MRVL", "side": "SELL",
                 "broker": "浙商", "quantity": 50, "price": 236.4, "fee": 2.26},
                {"id": "zs-sell-2", "date": "2026-10-01", "symbol": "MRVL", "side": "SELL",
                 "broker": "浙商", "quantity": 50, "price": 268.26, "fee": 2.28}]
        result = self.calculate(rows)
        self.assertEqual(result["holdings"], [])
        self.assertAlmostEqual(result["broker_accounts"]["浙商"]["realized_pnl_usd"], 3426.46)
        self.assertAlmostEqual(result["broker_accounts"]["国投"]["realized_pnl_usd"], -14491.6)

    def test_new_trade_still_defaults_date_but_import_does_not(self):
        self.assertEqual(monitor.normalize_trade({**self.sale(), "date": ""})["date"], dt.date.today().isoformat())
        imported = monitor.normalize_trade(self.opening())
        self.assertEqual(monitor.normalize_trade(imported)["date"], "")
        self.assertEqual(monitor.normalize_trade({**self.opening(), "date": "2026-05-20"})["date"], "2026-05-20")


if __name__ == "__main__":
    unittest.main()
