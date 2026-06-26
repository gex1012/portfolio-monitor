from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOCAL_TRADES_PATH = DATA_DIR / "streamlit_trades.json"
TRADE_HEADERS = [
    "id",
    "date",
    "side",
    "symbol",
    "fmp_symbol",
    "name",
    "quantity",
    "price",
    "currency",
    "fee",
    "note",
    "source",
    "created_by",
    "created_at",
]
AUDIT_HEADERS = ["timestamp", "user", "action", "symbol", "side", "quantity", "price", "note"]


st.set_page_config(page_title="Equity PnL Monitor", page_icon="📈", layout="wide")


def secret_value(*path: str, default: Any = None) -> Any:
    cur: Any = st.secrets
    try:
        for key in path:
            cur = cur[key]
        return cur
    except Exception:
        return default


def configure_core() -> Any:
    api_key = secret_value("fmp", "api_key", default=os.environ.get("FMP_API_KEY", ""))
    if api_key:
        os.environ["FMP_API_KEY"] = str(api_key)
    core = importlib.import_module("app")
    core.CONFIG["api_key"] = str(api_key or core.CONFIG.get("api_key", ""))
    core.CONFIG["account_base_hkd"] = float(secret_value("account", "base_hkd", default=core.CONFIG.get("account_base_hkd", 4_000_000)))
    core.CONFIG["share_password"] = str(secret_value("auth", "viewer_password", default=core.CONFIG.get("share_password", "")))
    return core


core = configure_core()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def to_float(value: Any) -> float:
    try:
        return core.to_number(value)
    except Exception:
        try:
            return float(str(value).replace(",", ""))
        except Exception:
            return 0.0


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.lower() in {"nan", "none"}:
        return ""
    return text.strip()


def google_sheet_enabled() -> bool:
    return bool(secret_value("google_sheets", "sheet_id", default="") and secret_value("gcp_service_account", "client_email", default=""))


def apps_script_enabled() -> bool:
    return bool(secret_value("apps_script", "url", default=""))


def cloud_ledger_enabled() -> bool:
    return apps_script_enabled() or google_sheet_enabled()


def apps_script_call(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = str(secret_value("apps_script", "url", default="")).strip()
    if not url:
        raise RuntimeError("Apps Script URL is not configured.")
    body = {
        "token": str(secret_value("apps_script", "token", default="")),
        "action": action,
        **(payload or {}),
    }
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "EquityPnLMonitor/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or f"Apps Script action failed: {action}"))
    return data


def service_account_info() -> dict[str, Any]:
    info = secret_value("gcp_service_account", default={})
    if isinstance(info, str):
        return json.loads(info)
    return dict(info)


@st.cache_resource(show_spinner=False)
def get_spreadsheet() -> Any:
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(service_account_info(), scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(str(secret_value("google_sheets", "sheet_id")))


def get_worksheet(name: str, headers: list[str]) -> Any | None:
    if not google_sheet_enabled():
        return None
    spreadsheet = get_spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=max(20, len(headers)))
    existing = worksheet.row_values(1)
    if not existing:
        worksheet.update([headers], "A1")
    return worksheet


def read_sheet_rows(name: str, headers: list[str]) -> list[dict[str, Any]]:
    worksheet = get_worksheet(name, headers)
    if worksheet is None:
        return []
    rows = worksheet.get_all_records()
    return [dict(row) for row in rows]


def append_sheet_row(name: str, headers: list[str], row: dict[str, Any]) -> None:
    worksheet = get_worksheet(name, headers)
    if worksheet is None:
        raise RuntimeError("Google Sheets is not configured.")
    worksheet.append_row([row.get(col, "") for col in headers], value_input_option="USER_ENTERED")


def load_local_rows() -> list[dict[str, Any]]:
    if not LOCAL_TRADES_PATH.exists():
        return []
    try:
        data = json.loads(LOCAL_TRADES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def append_local_row(row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_local_rows()
    rows.append(row)
    LOCAL_TRADES_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_trade(row: dict[str, Any]) -> dict[str, Any]:
    symbol = clean_text(row.get("symbol"))
    fmp_symbol = clean_text(row.get("fmp_symbol")) or core.fmp_symbol(symbol)
    currency = clean_text(row.get("currency")) or core.infer_currency(symbol)
    side = clean_text(row.get("side")).upper() or "BUY"
    qty = abs(to_float(row.get("quantity")))
    price = to_float(row.get("price"))
    fee = abs(to_float(row.get("fee"))) or core.calculated_fee(symbol, qty, price, currency)
    return {
        "id": clean_text(row.get("id")) or f"trade-{int(time.time() * 1000)}",
        "date": clean_text(row.get("date")) or dt.date.today().isoformat(),
        "side": "SELL" if side.startswith("S") else "BUY",
        "symbol": symbol,
        "fmp_symbol": fmp_symbol,
        "name": clean_text(row.get("name")) or symbol,
        "quantity": qty,
        "price": price,
        "currency": currency,
        "fee": fee,
        "note": clean_text(row.get("note")),
        "source": clean_text(row.get("source")) or "streamlit",
        "created_by": clean_text(row.get("created_by")) or "unknown",
        "created_at": clean_text(row.get("created_at")) or now_iso(),
    }


@st.cache_data(ttl=30, show_spinner=False)
def load_trades_cached(cache_key: str) -> list[dict[str, Any]]:
    if apps_script_enabled():
        rows = apps_script_call("read_trades").get("rows", [])
        return [normalize_trade(row) for row in rows if clean_text(row.get("symbol"))]
    if google_sheet_enabled():
        rows = read_sheet_rows(str(secret_value("google_sheets", "trades_worksheet", default="Trades")), TRADE_HEADERS)
        return [normalize_trade(row) for row in rows if clean_text(row.get("symbol"))]
    initial = core.excel_transactions()
    rows = initial.get("transactions", []) if initial.get("ok") else []
    rows.extend(load_local_rows())
    return [normalize_trade(row) for row in rows if clean_text(row.get("symbol"))]


def load_trades() -> list[dict[str, Any]]:
    key = "cloud" if cloud_ledger_enabled() else str(LOCAL_TRADES_PATH.stat().st_mtime if LOCAL_TRADES_PATH.exists() else 0)
    return load_trades_cached(key)


def append_trade(row: dict[str, Any]) -> None:
    trade = normalize_trade(row)
    audit = {
        "timestamp": now_iso(),
        "user": trade["created_by"],
        "action": "ADD_TRADE",
        "symbol": trade["fmp_symbol"],
        "side": trade["side"],
        "quantity": trade["quantity"],
        "price": trade["price"],
        "note": trade["note"],
    }
    if apps_script_enabled():
        apps_script_call("append_trade", {"trade": trade, "audit": audit})
    elif google_sheet_enabled():
        append_sheet_row(str(secret_value("google_sheets", "trades_worksheet", default="Trades")), TRADE_HEADERS, trade)
        append_sheet_row(str(secret_value("google_sheets", "audit_worksheet", default="Audit Log")), AUDIT_HEADERS, audit)
    else:
        append_local_row(trade)
    load_trades_cached.clear()


def load_audit() -> list[dict[str, Any]]:
    if apps_script_enabled():
        return list(apps_script_call("read_audit").get("rows", []))
    if not google_sheet_enabled():
        return []
    return read_sheet_rows(str(secret_value("google_sheets", "audit_worksheet", default="Audit Log")), AUDIT_HEADERS)


def compute_portfolio_from_trades(txs: list[dict[str, Any]]) -> dict[str, Any]:
    txs = sorted([normalize_trade(t) for t in txs], key=lambda x: (x.get("date") or "", x.get("id") or ""))
    quotes = core.quote_for_symbols([t["fmp_symbol"] for t in txs])
    fx_bundle = core.fx_rates_to_usd()
    fx = fx_bundle["to_usd"]
    positions: dict[str, dict[str, Any]] = {}
    realized_rows: list[dict[str, Any]] = []
    realized_total_usd = 0.0

    for t in txs:
        symbol = t["fmp_symbol"]
        pos = positions.setdefault(
            symbol,
            {
                "symbol": symbol,
                "raw_symbol": t["symbol"],
                "name": t.get("name") or symbol,
                "currency": t["currency"],
                "quantity": 0.0,
                "cost": 0.0,
                "realized_pnl": 0.0,
                "fees": 0.0,
                "last_trade_date": None,
            },
        )
        qty = float(t["quantity"])
        price = float(t["price"])
        fee = float(t.get("fee") or 0)
        pos["fees"] += fee
        pos["last_trade_date"] = t.get("date") or pos["last_trade_date"]
        if t["side"] == "BUY":
            pos["quantity"] += qty
            pos["cost"] += qty * price + fee
        else:
            avg_cost = pos["cost"] / pos["quantity"] if pos["quantity"] else 0.0
            sell_qty = min(qty, pos["quantity"]) if pos["quantity"] > 0 else qty
            pnl = (price - avg_cost) * sell_qty - fee
            pos["realized_pnl"] += pnl
            if pos["quantity"] > 0:
                pos["quantity"] -= sell_qty
                pos["cost"] -= avg_cost * sell_qty
            realized_usd = pnl * fx.get(pos["currency"], 1.0)
            realized_total_usd += realized_usd
            realized_rows.append(
                {
                    "date": t.get("date"),
                    "symbol": symbol,
                    "quantity": qty,
                    "price": price,
                    "avg_cost": avg_cost,
                    "realized_pnl_usd": realized_usd,
                    "source": t.get("source"),
                    "created_by": t.get("created_by"),
                }
            )

    projects = []
    unrealized_total_usd = 0.0
    market_value_total_usd = 0.0
    nq_ret = core.period_return("^NDX", 20)
    sp_ret = core.period_return("^GSPC", 20)
    for symbol, pos in positions.items():
        qty = pos["quantity"]
        quote = quotes.get(symbol.upper(), {})
        last = to_float(quote.get("price")) or to_float(quote.get("previousClose")) or (pos["cost"] / qty if qty else 0)
        avg_cost = pos["cost"] / qty if qty else 0.0
        rate = fx.get(pos["currency"], 1.0)
        stock_ret = core.period_return(symbol, 20)
        market_value_usd = qty * last * rate
        unrealized_usd = ((last - avg_cost) * qty if qty else 0.0) * rate
        market_value_total_usd += market_value_usd
        unrealized_total_usd += unrealized_usd
        projects.append(
            {
                **pos,
                "status": "active" if abs(qty) > 1e-9 else "closed",
                "avg_cost": avg_cost,
                "last_price": last,
                "changes_percentage": to_float(quote.get("changesPercentage") or quote.get("changePercentage")),
                "market_value_usd": market_value_usd,
                "unrealized_pnl_usd": unrealized_usd,
                "unrealized_pct": (last / avg_cost - 1) if avg_cost else 0,
                "return_20d": stock_ret,
                "rs_vs_nq_20d": (stock_ret - nq_ret) if stock_ret is not None and nq_ret is not None else None,
                "rs_vs_sp_20d": (stock_ret - sp_ret) if stock_ret is not None and sp_ret is not None else None,
                "fx_to_usd": rate,
            }
        )
    projects.sort(key=lambda x: (x["status"] != "active", -abs(x["market_value_usd"]), x["symbol"]))
    holdings = [p for p in projects if p["status"] == "active"]
    base_hkd = float(core.CONFIG.get("account_base_hkd", 4_000_000))
    base_usd = base_hkd * fx.get("HKD", 1 / 7.8)
    total_pnl_usd = realized_total_usd + unrealized_total_usd
    return {
        "fx": fx_bundle,
        "account": {
            "base_usd": base_usd,
            "equity_usd": base_usd + total_pnl_usd,
            "market_value_usd": market_value_total_usd,
            "total_pnl_usd": total_pnl_usd,
            "total_pnl_pct": total_pnl_usd / base_usd if base_usd else 0,
            "realized_pnl_usd": realized_total_usd,
            "unrealized_pnl_usd": unrealized_total_usd,
            "active_project_count": len(holdings),
            "closed_project_count": len(projects) - len(holdings),
        },
        "holdings": holdings,
        "projects": projects,
        "realized": realized_rows[-250:],
        "transactions": txs[-500:],
        "benchmarks": {"nq_return_20d": nq_ret, "sp_return_20d": sp_ret},
        "updated_at": now_iso(),
    }


ALIASES = {
    "英伟达": "NVDA",
    "辉达": "NVDA",
    "nvidia": "NVDA",
    "苹果": "AAPL",
    "apple": "AAPL",
    "特斯拉": "TSLA",
    "tesla": "TSLA",
    "微软": "MSFT",
    "microsoft": "MSFT",
    "谷歌": "GOOG",
    "google": "GOOG",
    "亚马逊": "AMZN",
    "amazon": "AMZN",
    "腾讯": "0700",
    "阿里": "9988",
    "美团": "3690",
    "小米": "1810",
    "中石化": "00386",
}


def parse_trade_text(raw: str, user: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError("请输入交易描述")
    lower = text.lower()
    side = "SELL" if any(x in lower for x in ["sell", "sold", "卖", "减仓", "清仓"]) else "BUY"
    qty_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:股|shares?|share)?", text, re.I)
    qty = to_float(qty_match.group(1)) if qty_match else 0
    if qty <= 0:
        raise ValueError("没有识别到数量，例如：买100股 英伟达")
    price_match = re.search(r"(?:@|at|价格|price)\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
    explicit_price = to_float(price_match.group(1)) if price_match else 0.0
    symbol = ""
    for name, ticker in ALIASES.items():
        if name.lower() in lower:
            symbol = ticker
            break
    if not symbol:
        ticker_match = re.search(r"\b([A-Za-z.]{1,8}|\d{3,6})\b", text)
        if ticker_match:
            symbol = ticker_match.group(1).upper()
    if not symbol:
        raise ValueError("没有识别到股票代码或名称")
    quote = core.latest_quote(symbol)
    price = explicit_price or to_float(quote.get("price"))
    if price <= 0:
        raise ValueError(f"没有拿到 {symbol} 实时价格，请手动输入价格")
    currency = core.infer_currency(symbol)
    fee = core.calculated_fee(symbol, qty, price, currency)
    return normalize_trade(
        {
            "side": side,
            "symbol": symbol,
            "quantity": qty,
            "price": price,
            "currency": currency,
            "fee": fee,
            "note": f"Parsed from: {text}",
            "created_by": user,
            "source": "streamlit_natural_language",
        }
    )


def role_from_password(password: str) -> str | None:
    admin = str(secret_value("auth", "admin_password", default=""))
    editor = str(secret_value("auth", "editor_password", default=""))
    viewer = str(secret_value("auth", "viewer_password", default=core.CONFIG.get("share_password", "")))
    if admin and password == admin:
        return "admin"
    if editor and password == editor:
        return "editor"
    if viewer and password == viewer:
        return "viewer"
    return None


def money(value: Any) -> str:
    num = to_float(value)
    return f"${num:,.0f}" if num >= 0 else f"-${abs(num):,.0f}"


def pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value) * 100:+.2f}%"


def login_gate() -> tuple[str, str]:
    if "role" not in st.session_state:
        st.session_state.role = None
    if "user_name" not in st.session_state:
        st.session_state.user_name = ""

    with st.sidebar:
        st.subheader("Access")
        if st.session_state.role:
            st.success(f"{st.session_state.user_name or 'User'} / {st.session_state.role}")
            if st.button("Log out"):
                st.session_state.role = None
                st.session_state.user_name = ""
                st.rerun()
        else:
            name = st.text_input("Name", placeholder="Your name")
            password = st.text_input("Password", type="password")
            if st.button("Enter", type="primary"):
                role = role_from_password(password)
                if role:
                    st.session_state.role = role
                    st.session_state.user_name = name.strip() or role
                    st.rerun()
                else:
                    st.error("Password is not correct.")
    if not st.session_state.role:
        st.title("Equity PnL Monitor")
        st.info("请输入访问密码。Viewer 只能查看，Editor/Admin 可以在网页里新增交易。")
        st.stop()
    return st.session_state.role, st.session_state.user_name or st.session_state.role


def render_overview(portfolio: dict[str, Any]) -> None:
    account = portfolio["account"]
    fx = portfolio["fx"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Account Equity", money(account["equity_usd"]))
    c2.metric("Total PnL", money(account["total_pnl_usd"]), pct(account["total_pnl_pct"]))
    c3.metric("Realized PnL", money(account["realized_pnl_usd"]))
    c4.metric("Unrealized PnL", money(account["unrealized_pnl_usd"]))
    spot = fx.get("spot", {})
    to_usd = fx.get("to_usd", {})
    st.caption(
        f"Spot FX used: USD/HKD {to_float(spot.get('USDHKD')):.4f} | "
        f"HKD/USD {to_float(to_usd.get('HKD')):.5f} | CNY/USD {to_float(to_usd.get('CNY')):.5f}"
    )

    holdings = pd.DataFrame(portfolio["holdings"])
    if holdings.empty:
        st.warning("No active holdings.")
        return
    cols = [
        "symbol",
        "quantity",
        "avg_cost",
        "last_price",
        "market_value_usd",
        "unrealized_pnl_usd",
        "unrealized_pct",
        "changes_percentage",
        "rs_vs_nq_20d",
        "rs_vs_sp_20d",
    ]
    st.subheader("Active Holdings")
    st.dataframe(holdings[cols].sort_values("market_value_usd", ascending=False), use_container_width=True, hide_index=True)


def render_trade_entry(role: str, user: str) -> None:
    st.subheader("Trade Entry")
    if role not in {"editor", "admin"}:
        st.info("Viewer 权限只能查看，不能新增交易。")
        return
    with st.form("natural_trade"):
        text = st.text_input("Natural language", placeholder="例：买100股 英伟达 / sell 20 NVDA @ 150")
        submitted = st.form_submit_button("Parse and save", type="primary")
    if submitted:
        try:
            trade = parse_trade_text(text, user)
            append_trade(trade)
            st.success(f"Saved {trade['side']} {trade['quantity']} {trade['fmp_symbol']} @ {trade['price']:.2f}; fee {trade['fee']:.2f}")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    with st.expander("Manual entry"):
        with st.form("manual_trade"):
            c1, c2, c3, c4 = st.columns(4)
            side = c1.selectbox("Side", ["BUY", "SELL"])
            symbol = c2.text_input("Symbol", placeholder="NVDA / 0700")
            qty = c3.number_input("Qty", min_value=0.0, step=1.0)
            price = c4.number_input("Price", min_value=0.0, step=0.01)
            c5, c6, c7 = st.columns(3)
            currency = c5.selectbox("Currency", ["", "USD", "HKD", "CNY"])
            fee = c6.number_input("Fee, blank/0 = auto", min_value=0.0, step=0.01)
            date = c7.date_input("Date", value=dt.date.today())
            note = st.text_input("Note")
            ok = st.form_submit_button("Save manual trade")
        if ok:
            try:
                append_trade(
                    {
                        "side": side,
                        "symbol": symbol,
                        "quantity": qty,
                        "price": price,
                        "currency": currency or core.infer_currency(symbol),
                        "fee": fee,
                        "date": date.isoformat(),
                        "note": note,
                        "created_by": user,
                        "source": "streamlit_manual",
                    }
                )
                st.success("Trade saved.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def render_stock_detail(portfolio: dict[str, Any]) -> None:
    symbols = [p["symbol"] for p in portfolio["projects"]]
    if not symbols:
        st.info("No stock projects yet.")
        return
    symbol = st.selectbox("Stock", symbols)
    with st.spinner("Loading stock detail..."):
        detail = core.stock_detail(symbol)
    tech = detail.get("technical", {})
    hist = pd.DataFrame(tech.get("history", []))
    if not hist.empty:
        st.line_chart(hist.set_index("date")[["close", "sma20", "sma50"]], use_container_width=True)
    advice = tech.get("advice", {})
    st.markdown("**短期：** " + str(advice.get("short_term", "-")))
    st.markdown("**中期：** " + str(advice.get("medium_term", "-")))
    st.write("技术信息")
    st.write(tech.get("signals", [])[:10])
    opt = detail.get("options", {})
    st.write("Options")
    st.json(opt.get("summary", {}), expanded=False)


def render_macro_indexes() -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Indexes")
        try:
            idx = core.index_overview()
            rows = pd.DataFrame(idx.get("items", []))
            if not rows.empty:
                st.dataframe(rows[["name", "last", "day_return", "return_5d", "return_20d", "return_60d", "trend", "comment"]], use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))
    with c2:
        st.subheader("Macro 24h")
        try:
            macro = core.macro_updates()
            for line in macro.get("analysis", []):
                st.write(line)
            rows = pd.DataFrame(macro.get("items", []))
            if not rows.empty:
                st.dataframe(rows[["date", "country", "event", "impact", "actual", "estimate", "previous", "category"]], use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))


def render_admin(role: str, portfolio: dict[str, Any]) -> None:
    st.subheader("Transactions")
    st.dataframe(pd.DataFrame(portfolio["transactions"]), use_container_width=True, hide_index=True)
    st.subheader("Realized PnL")
    st.dataframe(pd.DataFrame(portfolio["realized"]), use_container_width=True, hide_index=True)
    if role == "admin":
        st.subheader("Audit Log")
        audit = pd.DataFrame(load_audit())
        if audit.empty:
            st.info("Audit log is empty or Google Sheets is not configured.")
        else:
            st.dataframe(audit.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)


def main() -> None:
    role, user = login_gate()
    st.title("Equity PnL Monitor")
    if not cloud_ledger_enabled():
        st.warning("Cloud ledger is not configured. This run uses local fallback data; sharing needs Apps Script or Google Sheets secrets.")
    trades = load_trades()
    portfolio = compute_portfolio_from_trades(trades)
    tabs = st.tabs(["Overview", "Trade Entry", "Stock Detail", "Indexes & Macro", "Records"])
    with tabs[0]:
        render_overview(portfolio)
    with tabs[1]:
        render_trade_entry(role, user)
    with tabs[2]:
        render_stock_detail(portfolio)
    with tabs[3]:
        render_macro_indexes()
    with tabs[4]:
        render_admin(role, portfolio)


if __name__ == "__main__":
    main()
