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
        self.assertAlmostEqual(app.calculated_fee("0883.HK", 1000, 24.1, "HKD", broker="国投"), 128.06)

    def test_guotou_hk_itemised_contract_notes(self):
        # Line items printed on Guotou contract notes.
        self.assertEqual(app.guotou_hk_fee(50000, 4.70), {
            "commission": 235.0, "stamp": 235.0, "settlement": 9.87, "trans_levy": 6.35,
            "afrc_levy": 0.35, "trading_fee": 13.28, "total": 499.85})
        self.assertEqual(app.guotou_hk_fee(5100, 117.20), {
            "commission": 597.72, "stamp": 598.0, "settlement": 25.1, "trans_levy": 16.14,
            "afrc_levy": 0.9, "trading_fee": 33.77, "total": 1271.63})

    def test_guotou_hk_statement_totals_and_minimum_commission(self):
        for symbol, qty, price, side, expected in [
            ("0386.HK", 50000, 4.59, "BUY", 488.65),
            ("0386.HK", 50000, 4.63, "BUY", 492.90),
            ("9988.HK", 1000, 134.40, "BUY", 286.46),
            ("9618.HK", 3300, 116.20, "SELL", 816.17),
            ("0836.HK", 24000, 20.30, "SELL", 1037.07),
            ("0836.HK", 10000, 20.22, "SELL", 430.87),
            ("0836.HK", 8000, 20.70, "SELL", 352.64),
            ("0836.HK", 8000, 19.62, "SELL", 333.90),
            # Below HKD 100,000 notional the HKD 100 minimum commission applies.
            ("2338", 2000, 39.54, "BUY", 190.05),
            ("883", 4000, 20.86, "BUY", 194.59),
            ("0836.HK", 4000, 17.445, "SELL", 178.85),
            ("0883.HK", 2000, 24.10, "SELL", 155.11),
            ("0883", 2000, 23.06, "SELL", 152.87),
        ]:
            with self.subTest(symbol=symbol, qty=qty, price=price):
                self.assertEqual(app.calculated_fee(symbol, qty, price, "HKD", broker="国投", side=side), expected)
        self.assertEqual(app.calculated_fee("0883.HK", 2000, 24.10, "HKD"), 155.11)  # default broker is Guotou

    def test_guotou_us_statement_totals_and_minimum_commission(self):
        for symbol, qty, price, side, date, expected in [
            ("WEAT", 400, 24.06, "BUY", "2026-04-30", 20.00),
            ("LNG", 1, 290.95, "SELL", "2026-09-01", 20.01),
            ("AMAT", 20, 340, "SELL", "2026-11-05", 20.15),
            ("COHR", 30, 171.20, "SELL", "2026-11-05", 20.11),
            ("SLB", 400, 56.2958, "BUY", "2026-05-27", 45.04),
            ("COHR", 50, 409.8232, "SELL", "2026-06-25", 41.41),
            ("VLO", 100, 243.124, "SELL", "2026-05-14", 49.13),
            ("WEAT", 1000, 24.60, "SELL", "2026-08-13", 49.71),
            ("COHR", 30, 376, "SELL", "2026-08-07", 22.80),
        ]:
            with self.subTest(symbol=symbol, qty=qty, price=price):
                self.assertEqual(app.calculated_fee(symbol, qty, price, "USD", broker="国投", side=side, trade_date=date), expected)
        self.assertEqual(app.guotou_us_fee(400, 24.06, "BUY", "2026-04-30")["commission"], 20)

    def test_guotou_sec_statement_and_dates(self):
        self.assertEqual(app.calculated_fee("LNG", 90, 296, "USD", broker="国投", side="SELL", trade_date="2026-11-04"), 53.83)
        self.assertEqual(app.calculated_fee("MRVL", 100, 157, "USD", broker="国投", side="SELL", trade_date="2026-11-03T16:00:00Z"), 31.73)
        self.assertEqual(app.guotou_us_fee(90, 296, "BUY", "2026-11-04")["sec"], 0)
        self.assertEqual(app.guotou_us_fee(90, 296, "SELL", "2026-04-03")["sec"], 0)
        self.assertEqual(app.guotou_us_fee(90, 296, "SELL", "2026-04-03T16:00:00Z")["sec"], .55)

    def test_guotou_backfill_preserves_other_fees_and_is_idempotent(self):
        from backfill_guotou_sec import plan
        row = {"id": "one", "symbol": "MRVL", "currency": "USD", "quantity": 100,
               "price": 157, "side": "SELL", "date": "2026-11-04", "fee": 31.4, "broker": "国投"}
        changes, review = plan([row])
        self.assertEqual(changes[0]["new_fee"], 31.73)
        self.assertFalse(review)
        self.assertEqual(plan([{**row, "fee": 31.73}]), ([], []))
        self.assertEqual(plan([{**row, "broker": "浙商"}]), ([], []))
        self.assertEqual(plan([{**row, "fee": 35}]), ([], []))
        self.assertTrue(plan([{**row, "fee": 2}])[1])

    def test_zheshang_hk_notional_rate_and_minimum(self):
        for side in ["BUY", "SELL"]:
            for symbol, qty, price, expected in [
                ("0883.HK", 1000, 24.1, 5.0),
                ("883", 1000, 25, 5.0),
                ("0883.HK", 10000, 24.1, 48.2),
                ("0700.HK", 100, 500, 10.0),
            ]:
                with self.subTest(side=side, symbol=symbol, qty=qty):
                    self.assertEqual(app.calculated_fee(symbol, qty, price, "HKD", broker="浙商", side=side), expected)


if __name__ == "__main__":
    unittest.main()
