import unittest

from industry_allocation import build_industry_allocation, classify_security


HOLDINGS = [
    {"symbol": "EQT", "broker": "国投", "quantity": 100, "market_value_usd": 100, "unrealized_pnl_usd": 10},
    {"symbol": "EQT", "broker": "浙商", "quantity": 50, "market_value_usd": 50, "unrealized_pnl_usd": 5},
    {"symbol": "SOXX", "broker": "浙商", "quantity": 1, "market_value_usd": 50},
    {"symbol": "WEAT", "broker": "国投", "quantity": 1, "market_value_usd": 25},
    {"symbol": "XYZ", "broker": "国投", "quantity": 1, "market_value_usd": 25},
]


class IndustryAllocationTests(unittest.TestCase):
    def test_totals_counts_and_weights_across_brokers(self):
        result = build_industry_allocation(HOLDINGS, {}, nav=500)
        summary = result["summary"].set_index("category")
        self.assertEqual(result["gross_value_usd"], 250)
        self.assertAlmostEqual(summary["weight"].sum(), 1)
        self.assertEqual(summary.loc["能源", "market_value_usd"], 150)
        self.assertEqual(summary.loc["能源", "stock_count"], 1)
        self.assertEqual(summary.loc["能源", "weight"], 0.6)
        self.assertEqual(summary.loc["能源", "nav_weight"], 0.3)
        self.assertEqual(summary.loc["能源", "unrealized_pnl_usd"], 15)
        self.assertEqual(len(result["positions"]), 4)
        self.assertEqual(result["unknown_value_usd"], 25)

    def test_broker_filter_rebases_weights(self):
        result = build_industry_allocation(HOLDINGS, {}, broker="浙商", nav=200)
        self.assertEqual(result["gross_value_usd"], 100)
        self.assertEqual(result["summary"]["weight"].tolist(), [0.5, 0.5])

    def test_etfs_use_investment_exposure_not_manager_sector(self):
        profile = {"sector": "Financial Services", "industry": "Asset Management", "isEtf": True}
        self.assertEqual(classify_security("SOXX", profile)["sector"], "信息技术")
        self.assertEqual(classify_security("WEAT", profile)["sector"], "商品")
        self.assertEqual(classify_security("OTHERETF", profile)["sector"], "基金 / 待穿透")

    def test_live_profile_overrides_fallback_and_bad_payload_is_safe(self):
        self.assertEqual(classify_security("EQT", {"sector": "Industrials", "industry": "New category"})["sector"], "工业")
        self.assertEqual(classify_security("EQT", [])["sector"], "能源")
        self.assertEqual(classify_security("NEW", None)["sector"], "未分类")

    def test_shorts_do_not_disappear_when_netting_across_brokers(self):
        holdings = [{**HOLDINGS[0]}, {**HOLDINGS[1], "quantity": -50, "market_value_usd": -50}]
        result = build_industry_allocation(holdings, {}, nav=200)
        self.assertTrue(result["has_shorts"])
        self.assertEqual(result["gross_value_usd"], 150)
        self.assertEqual(result["summary"].iloc[0]["market_value_usd"], 50)
        self.assertEqual(result["summary"].iloc[0]["weight"], 1)

    def test_empty_zero_and_industry_view(self):
        self.assertFalse(build_industry_allocation([], {})["ok"])
        self.assertFalse(build_industry_allocation([{**HOLDINGS[0], "quantity": 0}], {})["ok"])
        self.assertFalse(build_industry_allocation(HOLDINGS, {}, broker="missing")["ok"])
        result = build_industry_allocation(HOLDINGS, {}, level="industry")
        self.assertIn("油气勘探与开采", result["summary"]["category"].tolist())


if __name__ == "__main__":
    unittest.main()
