import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as core
import streamlit_app as monitor
from corporate_actions import (normalize_splits, portfolio_timeline, apply_split,
                               adjust_raw_history, is_effective, validate_split_quotes, SplitQuotePending)


class SplitTests(unittest.TestCase):
    def event(self, numerator=3, denominator=1, date="2026-11-05", symbol="SOXX"):
        return normalize_splits(symbol, [{"date": date, "numerator": numerator, "denominator": denominator}], "test")[0]

    def trade(self, side="BUY", qty=30, price=531.05, date="2026-08-01", broker="浙商"):
        return {"id": f"{broker}-{side}-{date}", "symbol": "SOXX", "fmp_symbol": "SOXX", "date": date,
                "side": side, "quantity": qty, "price": price, "fee": 2, "currency": "USD", "broker": broker}

    def calculate(self, trades, events, price=177.0388888889):
        with patch.object(core, "stock_split_events", return_value={"events": events, "warnings": []}), \
             patch.object(core, "quote_for_symbols", return_value={"SOXX": {"price": price}}), \
             patch.object(core, "fx_rates_to_usd", return_value={"to_usd": {"USD": 1, "HKD": 1 / 7.8}}), \
             patch.object(core, "period_return", return_value=None), \
             patch.object(monitor, "period_return_ytd", return_value=None), \
             patch.object(monitor, "load_dividend_records", return_value=[]):
            return monitor.compute_portfolio_from_trades(trades)

    def test_forward_split_cost_and_pnl_invariant(self):
        trade = self.trade()
        before = copy.deepcopy(trade)
        result = self.calculate([trade], [self.event()])
        pos = result["holdings"][0]
        self.assertEqual(pos["quantity"], 90)
        self.assertAlmostEqual(pos["cost"], 15933.5)
        self.assertAlmostEqual(pos["avg_cost"], 15933.5 / 90)
        self.assertAlmostEqual(result["account"]["total_pnl_usd"], 0)
        self.assertEqual(trade, before)
        self.assertEqual(len(result["transactions"]), 1)

    def test_reverse_arbitrary_ratio_and_fractional_shares(self):
        result = self.calculate([self.trade(qty=31)], [self.event(2, 7)])
        pos = result["holdings"][0]
        self.assertAlmostEqual(pos["quantity"], 31 * 2 / 7)
        self.assertAlmostEqual(pos["cost"], 31 * 531.05 + 2)
        self.assertTrue(result["split_adjustments"][0]["fractional"])

    def test_same_day_sale_uses_adjusted_cost(self):
        trades = [self.trade(), self.trade("SELL", 30, 180, "2026-11-05")]
        result = self.calculate(trades, [self.event()], price=180)
        self.assertEqual(result["holdings"][0]["quantity"], 60)
        self.assertAlmostEqual(result["account"]["realized_pnl_usd"], 5400 - 15933.5 / 3 - 2)
        self.assertAlmostEqual(result["account"]["total_pnl_usd"], 90 * 180 - 15933.5 - 2)

    def test_multiple_splits_and_replay_are_idempotent(self):
        events = [self.event(5, 2, "2026-09-01"), self.event(1, 10)]
        events.append(events[0])
        rows = [self.trade()]
        first = self.calculate(rows, events)
        second = self.calculate(rows, events)
        self.assertEqual(first["holdings"][0]["quantity"], 7.5)
        self.assertEqual(second["holdings"][0]["quantity"], 7.5)
        self.assertEqual(len(first["split_adjustments"]), 2)

    def test_closed_position_and_post_split_purchase_not_adjusted(self):
        rows = [self.trade(), self.trade("SELL", 30, 540, "2026-09-01"),
                self.trade(qty=10, price=180, date="2026-11-05")]
        result = self.calculate(rows, [self.event()])
        self.assertEqual(result["holdings"][0]["quantity"], 10)
        self.assertEqual(result["split_adjustments"], [])

    def test_two_brokers_and_future_split(self):
        rows = [self.trade(), self.trade(qty=10, broker="国投")]
        result = self.calculate(rows, [self.event(), self.event(7, 1, "2099-01-01")])
        positions = {p["broker"]: p for p in result["holdings"]}
        self.assertEqual(positions["浙商"]["quantity"], 90)
        self.assertEqual(positions["国投"]["quantity"], 30)

    def test_effective_at_exchange_open_not_record_date(self):
        event = self.event()
        self.assertFalse(is_effective(event, dt.datetime(2026, 11, 5, 14, 29, tzinfo=dt.timezone.utc)))
        self.assertTrue(is_effective(event, dt.datetime(2026, 11, 5, 14, 30, tzinfo=dt.timezone.utc)))

    def test_sheets_date_and_undated_opening(self):
        sale = self.trade("SELL", 90, 180, "2026-11-04T16:00:00.000Z")
        opening = {**self.trade(), "date": "", "id": "excel-1-buy", "source": "initial_excel"}
        result = self.calculate([sale, opening], [self.event()])
        self.assertEqual(result["holdings"], [])

    def test_undated_snapshot_does_not_receive_ancient_splits(self):
        opening = {**self.trade(), "date": "", "id": "excel-1-buy", "source": "initial_excel"}
        sale = self.trade("SELL", 90, 180, "2026-11-05")
        result = self.calculate([opening, sale], [self.event(10, 1, "2006-01-01"), self.event()])
        self.assertEqual(result["holdings"], [])
        self.assertEqual(len(result["split_adjustments"]), 1)

    def test_reject_invalid_and_conflicting_ratios(self):
        for ratio in [0, -2, float("nan"), float("inf")]:
            self.assertEqual(normalize_splits("X", [{"date": "2026-11-05", "numerator": ratio, "denominator": 1}], "test"), [])
        with self.assertRaises(ValueError):
            normalize_splits("X", [{"date": "2026-11-05", "numerator": n, "denominator": 1} for n in (2, 3)], "test")

    def test_raw_history_adjustment_and_stale_quote_guard(self):
        rows = [{"date": "2026-11-04", "open": 540, "high": 600, "low": 510, "close": 570, "volume": 100}]
        adjusted = adjust_raw_history(rows, [self.event()])
        self.assertEqual(adjusted[0]["close"], 190)
        self.assertEqual(adjusted[0]["volume"], 300)
        self.assertEqual(rows[0]["close"], 570)
        with self.assertRaises(SplitQuotePending):
            validate_split_quotes([self.event()], {"SOXX": {"timestamp": dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc).timestamp()}})

    def test_provider_cache_outage_and_soxx_issuer_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core, "DATA_DIR", Path(directory)), \
             patch.object(core, "CACHE", {}), patch.object(core, "yahoo_split_events", return_value=None), \
             patch.object(core, "fmp_get", return_value=[
                 {"date": "2026-11-06", "numerator": 3, "denominator": 1}]) as fetch:
            result = core.stock_split_events(["soxx", "SOXX"])
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(result["events"][0]["date"], "2026-11-05")
            core.CACHE.clear()
            fetch.return_value = {"_error": "timeout"}
            self.assertEqual(core.stock_split_events(["SOXX"])["events"][0]["date"], "2026-11-05")
            self.assertTrue(core.stock_split_events(["SOXX"])["warnings"])

    def test_secondary_split_feed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core, "DATA_DIR", Path(directory)), \
             patch.object(core, "CACHE", {}), patch.object(core, "fmp_get", return_value={"_error": "coverage"}), \
             patch.object(core, "yahoo_split_events", return_value=[{"date": "2026-10-01", "numerator": 1, "denominator": 5}]):
            result = core.stock_split_events(["0883.HK"])
            self.assertEqual(result["events"][0]["ratio"], .2)
            self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()
