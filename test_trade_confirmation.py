import datetime as dt
import unittest

from streamlit.testing.v1 import AppTest


HARNESS = '''
import streamlit as st
import streamlit_app as app

app.core.latest_quote = lambda symbol: {"price": 900}
def save(trade):
    st.session_state.setdefault("saved", []).append(dict(trade))
def update(trade, user):
    st.session_state.setdefault("updated", []).append(dict(trade))
    return "cloud"
app.append_trade = save
app.update_trade_record = update
def manager(role, user):
    if st.button("Stage edit"):
        app.stage_trade_confirmation({"id": "edit-1", "symbol": "MU", "side": "SELL", "quantity": 20,
            "price": 900, "currency": "USD", "broker": "浙商", "date": "2026-10-19", "fee": 2.38},
            user, mode="update", auto_fee=False)
app.render_trade_record_manager = manager
app.render_trade_entry("editor", "Tester")
st.session_state.normalized_legacy = app.normalize_dividend_row({"symbol": "SOXX", "source": "streamlit_dividend|broker=浙商", "fee": 1})
st.session_state.normalized_default = app.normalize_dividend_row({"symbol": "AVGO"})
'''


def find(elements, label):
    return next(element for element in elements if element.label == label)


class TradeConfirmationTests(unittest.TestCase):
    def app(self):
        result = AppTest.from_string(HARNESS, default_timeout=20).run()
        self.assertEqual(len(result.exception), 0)
        return result

    def natural_preview(self, app):
        find(app.text_input, "Natural language").set_value("sell 20 MU @ 900")
        find(app.button, "预览并确认").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn("saved", app.session_state)
        self.assertTrue(find(app.button, "确认并保存").disabled)

    def test_cancel_does_not_write(self):
        app = self.app()
        self.natural_preview(app)
        find(app.button, "返回修改").click().run()
        self.assertNotIn("pending_trade_confirmation", app.session_state)
        self.assertNotIn("saved", app.session_state)

    def test_broker_switch_recalculates_before_save(self):
        app = self.app()
        self.natural_preview(app)
        find(app.checkbox, "确认本笔交易属于「国投」账户").check().run()
        find(app.selectbox, "确认券商").select("浙商").run()
        self.assertTrue(find(app.button, "确认并保存").disabled)
        self.assertEqual(find(app.metric, "本次记录手续费").value, "$2.38")
        find(app.checkbox, "确认本笔交易属于「浙商」账户").check().run()
        find(app.button, "确认并保存").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state.saved), 1)
        self.assertEqual(app.session_state.saved[0]["broker"], "浙商")
        self.assertEqual(app.session_state.saved[0]["fee"], 2.38)
        app.run()
        self.assertEqual(len(app.session_state.saved), 1)

    def test_manual_backdated_sale_uses_dated_fees(self):
        app = self.app()
        find(app.selectbox, "Side").select("SELL")
        find(app.text_input, "Symbol").set_value("MRVL")
        find(app.number_input, "Qty").set_value(50)
        find(app.number_input, "Price").set_value(236.4)
        find(app.selectbox, "Currency").select("USD")
        app.selectbox(key="manual_trade_broker").select("浙商")
        find(app.date_input, "Date").set_value(dt.date(2026, 8, 19))
        find(app.button, "预览并确认手动交易").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertNotIn("saved", app.session_state)
        self.assertEqual(find(app.metric, "本次记录手续费").value, "$2.26")

    def test_edit_uses_confirmation_and_keeps_id(self):
        app = self.app()
        find(app.button, "Stage edit").click().run()
        self.assertNotIn("updated", app.session_state)
        find(app.checkbox, "确认本笔交易属于「浙商」账户").check().run()
        find(app.button, "确认并保存").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state.updated[0]["id"], "edit-1")
        self.assertNotIn("saved", app.session_state)

    def test_manual_fee_is_preserved_on_confirmation(self):
        app = self.app()
        self.natural_preview(app)
        find(app.checkbox, "手动指定总手续费").check().run()
        find(app.number_input, "总手续费").set_value(9.99).run()
        find(app.selectbox, "确认券商").select("浙商").run()
        find(app.checkbox, "确认本笔交易属于「浙商」账户").check().run()
        find(app.button, "确认并保存").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state.saved[0]["fee"], 9.99)
        self.assertEqual(app.session_state.saved[0]["broker"], "浙商")

    def test_legacy_dividend_broker_round_trip(self):
        app = self.app()
        self.assertEqual(app.session_state.normalized_legacy["broker"], "浙商")
        self.assertEqual(app.session_state.normalized_legacy["fee"], 1)
        self.assertEqual(app.session_state.normalized_default["broker"], "国投")


if __name__ == "__main__":
    unittest.main()
