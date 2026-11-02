import unittest

from streamlit.testing.v1 import AppTest


HARNESS = '''
import streamlit_app as app
from industry_allocation import classify_security
from test_industry_allocation import HOLDINGS
app.load_industry_classifications = lambda symbols: {symbol: classify_security(symbol) for symbol in symbols}
app.build_risk_assessment = lambda portfolio: {"ok": False, "note": "Price history unavailable"}
app.render_risk_assessment({"holdings": HOLDINGS, "account": {"equity_usd": 500},
    "broker_accounts": {"国投": {"equity_usd": 300}, "浙商": {"equity_usd": 200}}})
'''


class IndustryViewTests(unittest.TestCase):
    def test_sector_view_is_available_without_price_history(self):
        app = AppTest.from_string(HARNESS, default_timeout=20).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, "$250")
        summary = app.dataframe[0].value
        self.assertEqual(summary["市值 USD"].sum(), 250)
        self.assertEqual(summary["持仓占比"].sum(), 1)
        app.selectbox(key="industry_detail").select("能源").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.dataframe[1].value["股票"].tolist(), ["EQT"])
        self.assertEqual(app.dataframe[1].value.iloc[0]["股数"], 150)

    def test_broker_and_industry_controls(self):
        app = AppTest.from_string(HARNESS, default_timeout=20).run()
        app.selectbox(key="industry_broker").select("浙商").run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, "$100")
        app.radio(key="industry_level").set_value("细分行业").run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("半导体 ETF", app.dataframe[0].value["行业"].tolist())


if __name__ == "__main__":
    unittest.main()
