import datetime as dt
import unittest

import pandas as pd

import streamlit_app as app


class LocalDateTests(unittest.TestCase):
    def test_cloud_ledger_instant_becomes_utc8_date(self):
        self.assertEqual(app.local_date("2026-06-28T16:00:00.000Z"), dt.date(2026, 6, 29))
        self.assertEqual(app.local_date_text("2026-11-09T16:00:00.000Z"), "2026-11-10")

    def test_plain_dates_are_unchanged(self):
        self.assertEqual(app.local_date("2026-06-29"), dt.date(2026, 6, 29))
        self.assertEqual(app.local_date_text("2026-07-06"), "2026-07-06")

    def test_blank_and_unparseable_values(self):
        self.assertIsNone(app.local_date(""))
        self.assertIsNone(app.local_date(None))
        self.assertEqual(app.local_date_text(""), "")
        self.assertEqual(app.local_date_text("not a date"), "not a date")

    def test_table_copy_shows_local_dates_and_keeps_the_source(self):
        frame = pd.DataFrame({"date": ["2026-06-28T16:00:00.000Z", "2026-07-06", ""], "symbol": ["A", "B", "C"]})
        shown = app.with_local_dates(frame)
        self.assertEqual(shown["date"].tolist(), ["2026-06-29", "2026-07-06", ""])
        self.assertEqual(frame["date"].iloc[0], "2026-06-28T16:00:00.000Z")
        empty = pd.DataFrame()
        self.assertIs(app.with_local_dates(empty), empty)


if __name__ == "__main__":
    unittest.main()
