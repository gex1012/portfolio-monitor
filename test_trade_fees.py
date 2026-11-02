import unittest

import app


class TradeFeeTests(unittest.TestCase):
    def test_contract_notes(self):
        for qty, price, side, date, expected in [
            (20, 948, "SELL", "2026-08-13", 2.41),
            (50, 320.8, "BUY", "2026-08-18", 2.00),
            (50, 236.4, "SELL", "2026-08-19", 2.26),
            (20, 900, "SELL", "2026-10-19", 2.38),
        ]:
            with self.subTest(date=date, side=side):
                self.assertEqual(app.calculated_fee("MU", qty, price, "USD", broker="浙商", side=side, trade_date=date), expected)

    def test_minimum_and_per_share(self):
        self.assertEqual(app.zheshang_us_fee(250, 100, "BUY", "2026-08-01")["commission"], 2)
        self.assertEqual(app.zheshang_us_fee(1000, 100, "BUY", "2026-08-01")["commission"], 8)

    def test_regulatory_dates_and_cap(self):
        self.assertEqual(app.zheshang_us_fee(50, 100, "SELL", "2026-04-03")["sec"], 0)
        self.assertEqual(app.zheshang_us_fee(50, 100, "SELL", "2026-04-06")["sec"], 0.11)
        self.assertEqual(app.zheshang_us_fee(50, 100, "SELL", "2026-09-30T16:00:00Z")["taf"], 0)
        self.assertEqual(app.zheshang_us_fee(100000, 100, "SELL", "2026-08-01")["taf"], 9.79)

    def test_existing_broker_and_hk_unchanged(self):
        self.assertAlmostEqual(app.calculated_fee("VRT", 50, 234.5, "USD", broker="国投"), 23.45)
        self.assertAlmostEqual(app.calculated_fee("0883.HK", 1000, 24.1, "HKD", broker="浙商"), 50.61)


if __name__ == "__main__":
    unittest.main()
