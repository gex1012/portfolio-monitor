import unittest

from streamlit.testing.v1 import AppTest


HARNESS = '''
import streamlit_app as app
from unittest.mock import patch
from contextlib import ExitStack
with ExitStack() as stack:
    for target, name, value in [
        (app.core, "stock_split_events", {"events": [], "warnings": []}),
        (app.core, "quote_for_symbols", {}),
        (app.core, "fx_rates_to_usd", {"to_usd": {"USD": 1, "HKD": 0.125}}),
        (app.core, "period_return", None),
        (app, "period_return_ytd", None),
        (app, "load_dividend_records", []),
        (app, "render_index_strip", None),
        (app, "render_holding_date_alerts", None),
    ]:
        stack.enter_context(patch.object(target, name, return_value=value))
    app.render_overview(app.compute_portfolio_from_trades([]))
'''


class EquityViewTests(unittest.TestCase):
    def test_total_and_broker_equity_show_hkd_and_usd(self):
        app = AppTest.from_string(HARNESS, default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(metric.label == "Account Equity (USD)" for metric in app.metric))
        self.assertTrue(any("HK$6,363,970.42" in caption.value for caption in app.caption))
        table = app.dataframe[0].value
        self.assertIn("Equity (USD)", table.columns)
        self.assertIn("Equity (HKD)", table.columns)
        self.assertAlmostEqual(table["Equity (HKD)"].sum(), 6_363_970.42)

    def test_initial_equity_shown_for_each_broker_and_total(self):
        app = AppTest.from_string(HARNESS, default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        table = app.dataframe[0].value.set_index("Broker")
        self.assertAlmostEqual(table.loc["国投", "Initial Equity (HKD)"], 4_363_970.42)
        self.assertAlmostEqual(table.loc["浙商", "Initial Equity (HKD)"], 2_000_000.0)
        self.assertAlmostEqual(table.loc["国投", "Initial Equity (USD)"], 4_363_970.42 * 0.125)
        self.assertNotIn("Base", table.columns)
        caption = next(c.value for c in app.caption if c.value.startswith("Initial Equity"))
        for text in ["HK$6,363,970.42", "国投 HK$4,363,970.42", "浙商 HK$2,000,000.00"]:
            self.assertIn(text, caption)


if __name__ == "__main__":
    unittest.main()
