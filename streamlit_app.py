from __future__ import annotations

import datetime as dt
import html
import importlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


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
    nq_ytd = period_return_ytd("^NDX")
    sp_ytd = period_return_ytd("^GSPC")
    for symbol, pos in positions.items():
        qty = pos["quantity"]
        quote = quotes.get(symbol.upper(), {})
        last = to_float(quote.get("price")) or to_float(quote.get("previousClose")) or (pos["cost"] / qty if qty else 0)
        avg_cost = pos["cost"] / qty if qty else 0.0
        rate = fx.get(pos["currency"], 1.0)
        stock_ret = core.period_return(symbol, 20)
        stock_ytd = period_return_ytd(symbol)
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
                "return_ytd": stock_ytd,
                "rs_vs_nq_20d": (stock_ret - nq_ret) if stock_ret is not None and nq_ret is not None else None,
                "rs_vs_sp_20d": (stock_ret - sp_ret) if stock_ret is not None and sp_ret is not None else None,
                "rs_vs_nq_ytd": (stock_ytd - nq_ytd) if stock_ytd is not None and nq_ytd is not None else None,
                "rs_vs_sp_ytd": (stock_ytd - sp_ytd) if stock_ytd is not None and sp_ytd is not None else None,
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
        "benchmarks": {"nq_return_20d": nq_ret, "sp_return_20d": sp_ret, "nq_return_ytd": nq_ytd, "sp_return_ytd": sp_ytd},
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


def compact_number(value: Any, decimals: int = 2) -> str:
    if value in (None, ""):
        return "-"
    try:
        num = float(value)
    except Exception:
        text = clean_text(value)
        return text or "-"
    if pd.isna(num):
        return "-"
    text = f"{num:,.{decimals}f}"
    return text.rstrip("0").rstrip(".")


def compact_large_number(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        num = float(str(value).replace(",", ""))
    except Exception:
        return clean_text(value) or "-"
    if pd.isna(num):
        return "-"
    sign = "-" if num < 0 else ""
    num = abs(num)
    units = [(1_000_000_000_000, "T"), (1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")]
    for base, suffix in units:
        if num >= base:
            text = f"{num / base:.2f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    return f"{sign}{compact_number(num)}"


def compact_pct(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        num = float(value)
    except Exception:
        return clean_text(value) or "-"
    if pd.isna(num):
        return "-"
    return f"{num * 100:+.2f}%"


def safe_html(value: Any) -> str:
    return html.escape(clean_text(value) or "-")


def period_return_ytd(symbol: str) -> float | None:
    rows = core.historical_prices(symbol)
    year = dt.date.today().year
    ytd_rows: list[dict[str, Any]] = []
    for row in rows:
        try:
            row_date = dt.date.fromisoformat(str(row.get("date", ""))[:10])
        except Exception:
            continue
        close = to_float(row.get("close"))
        if row_date.year == year and close > 0:
            ytd_rows.append(row)
    if len(ytd_rows) < 2:
        return None
    start = to_float(ytd_rows[0].get("close"))
    end = to_float(ytd_rows[-1].get("close"))
    return (end / start - 1) if start else None


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
          padding-top: 2rem;
          padding-bottom: 2.5rem;
          max-width: 1500px;
        }
        h1 {
          letter-spacing: 0;
          margin-bottom: 0.4rem;
        }
        div[data-testid="stMetric"] {
          background: #ffffff;
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          padding: 14px 16px;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
        }
        div[data-testid="stMetricLabel"] p {
          color: #64748b;
          font-size: 0.84rem;
        }
        div[data-testid="stMetricValue"] {
          color: #172033;
          font-weight: 700;
        }
        .holding-summary {
          display: grid;
          grid-template-columns: repeat(4, minmax(150px, 1fr));
          gap: 10px;
          margin: 8px 0 12px;
        }
        .holding-card {
          border: 1px solid #e5e7eb;
          border-left: 4px solid #2563eb;
          border-radius: 8px;
          background: #fff;
          padding: 10px 12px;
        }
        .holding-card span {
          display: block;
          color: #64748b;
          font-size: 12px;
          margin-bottom: 4px;
        }
        .holding-card strong {
          color: #172033;
          font-size: 18px;
        }
        .section-note {
          color: #64748b;
          font-size: 13px;
          margin-bottom: 8px;
        }
        .detail-grid {
          display: grid;
          grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.65fr);
          gap: 14px;
          align-items: start;
          margin-top: 10px;
        }
        .panel-card {
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          background: #ffffff;
          padding: 12px 14px;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
          margin-bottom: 12px;
        }
        .panel-card h4 {
          margin: 0 0 8px;
          color: #172033;
          font-size: 15px;
        }
        .panel-card p,
        .panel-card li {
          color: #334155;
          line-height: 1.45;
          font-size: 13px;
        }
        .panel-card ul {
          margin: 0;
          padding-left: 18px;
        }
        .mini-bar-row {
          display: grid;
          grid-template-columns: 72px minmax(0, 1fr) 82px;
          gap: 8px;
          align-items: center;
          margin: 6px 0;
          color: #475569;
          font-size: 12px;
        }
        .mini-track {
          height: 9px;
          border-radius: 999px;
          background: #eef2f7;
          overflow: hidden;
        }
        .mini-fill {
          height: 100%;
          border-radius: 999px;
          background: #176b87;
        }
        .mini-fill.put {
          background: #a66a00;
        }
        .news-link {
          color: #176b87;
          text-decoration: none;
          font-weight: 600;
        }
        .index-strip {
          display: grid;
          grid-template-columns: repeat(3, minmax(220px, 1fr));
          gap: 10px;
          margin: 14px 0 18px;
        }
        .index-card {
          border: 1px solid #e5e7eb;
          border-left: 4px solid #176b87;
          border-radius: 8px;
          background: #fff;
          padding: 12px;
          min-height: 126px;
        }
        .index-card h4 {
          display: flex;
          justify-content: space-between;
          margin: 0 0 8px;
          color: #172033;
          font-size: 15px;
        }
        .index-card h4 span {
          color: #64748b;
          font-weight: 600;
          font-size: 12px;
        }
        .index-price {
          font-size: 20px;
          font-weight: 700;
          color: #172033;
          margin-bottom: 8px;
        }
        .index-returns {
          display: grid;
          grid-template-columns: repeat(4, auto);
          justify-content: start;
          gap: 8px;
          font-size: 12px;
          margin-bottom: 8px;
        }
        .index-comment {
          color: #475569;
          font-size: 12px;
          line-height: 1.4;
        }
        .index-returns-table {
          width: 100%;
          border-collapse: collapse;
          margin: 8px 0 8px;
          table-layout: fixed;
        }
        .index-returns-table th {
          color: #64748b;
          font-size: 11px;
          font-weight: 700;
          text-align: left;
          padding: 4px 4px 3px 0;
          border-bottom: 1px solid #e5e7eb;
        }
        .index-returns-table td {
          font-size: 13px;
          font-weight: 700;
          padding: 5px 4px 2px 0;
          white-space: nowrap;
        }
        .macro-brief-card {
          border: 1px solid #e5e7eb;
          border-radius: 8px;
          background: #ffffff;
          padding: 16px 18px 14px;
          min-height: 236px;
          box-shadow: 0 1px 2px rgba(15, 23, 42, 0.035);
        }
        .macro-brief-card h4 {
          margin: 0 0 12px;
          color: #172033;
          font-size: 17px;
          line-height: 1.25;
          font-weight: 750;
        }
        .macro-brief-card ul {
          margin: 0;
          padding: 0;
          list-style: none;
        }
        .macro-brief-card li {
          position: relative;
          margin: 0 0 12px;
          padding-left: 18px;
          color: #253247;
          font-size: 14.5px;
          line-height: 1.75;
        }
        .macro-brief-card li::before {
          content: "";
          position: absolute;
          left: 0;
          top: 0.78em;
          width: 5px;
          height: 5px;
          border-radius: 999px;
          background: #2563eb;
        }
        .macro-brief-card strong {
          color: #0f172a;
          font-weight: 750;
        }
        div[data-testid="stDataFrame"] {
          font-size: 13px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def color_signed(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return ""
    if num > 0:
        return "color: #15803d; font-weight: 600"
    if num < 0:
        return "color: #b91c1c; font-weight: 600"
    return "color: #475569"


def render_candlestick_chart(rows: list[dict[str, Any]]) -> None:
    data = rows[-170:]
    if not data:
        st.info("No price history.")
        return
    chart_data = json.dumps(data, ensure_ascii=False, default=str)
    html = """
    <div id="klineWrap" style="position:relative;border:1px solid #e5e7eb;border-radius:8px;background:#fff;overflow:hidden;">
      <canvas id="klineCanvas" width="980" height="390" style="width:100%;height:390px;display:block;"></canvas>
      <div id="klineTip" style="display:none;position:absolute;z-index:5;min-width:188px;padding:9px 10px;border:1px solid #dbe3ee;border-radius:8px;background:rgba(255,255,255,0.96);box-shadow:0 8px 24px rgba(15,23,42,0.14);font:12px Arial;color:#172033;pointer-events:none;line-height:1.45;"></div>
    </div>
    <script>
    const rows = __DATA__;
    const wrap = document.getElementById("klineWrap");
    const canvas = document.getElementById("klineCanvas");
    const tip = document.getElementById("klineTip");
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    const pad = { l: 54, r: 22, t: 28, b: 42 };
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);

    const vals = [];
    rows.forEach(r => {
      ["high", "low", "sma20", "sma50"].forEach(k => {
        const v = Number(r[k]);
        if (Number.isFinite(v) && v > 0) vals.push(v);
      });
    });
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const x = i => pad.l + (i / Math.max(1, rows.length - 1)) * (w - pad.l - pad.r);
    const y = v => pad.t + (max - v) / Math.max(0.0001, max - min) * (h - pad.t - pad.b);

    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 1;
    ctx.font = "12px Arial";
    ctx.fillStyle = "#64748b";
    for (let i = 0; i < 5; i++) {
      const yy = pad.t + i * (h - pad.t - pad.b) / 4;
      const price = max - i * (max - min) / 4;
      ctx.beginPath();
      ctx.moveTo(pad.l, yy);
      ctx.lineTo(w - pad.r, yy);
      ctx.stroke();
      ctx.fillText(price.toFixed(2), 8, yy + 4);
    }

    rows.forEach((r, i) => {
      const xx = x(i);
      const open = Number(r.open), close = Number(r.close), high = Number(r.high), low = Number(r.low);
      if (![open, close, high, low].every(Number.isFinite)) return;
      const up = close >= open;
      const color = up ? "#2f8f6f" : "#b64242";
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(xx, y(low));
      ctx.lineTo(xx, y(high));
      ctx.stroke();
      const top = y(Math.max(open, close));
      const bot = y(Math.min(open, close));
      ctx.fillRect(xx - 2.4, top, 4.8, Math.max(1, bot - top));
    });

    function drawLine(key, color) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      let started = false;
      rows.forEach((r, i) => {
        const v = Number(r[key]);
        if (!Number.isFinite(v) || v <= 0) return;
        if (!started) {
          ctx.moveTo(x(i), y(v));
          started = true;
        } else {
          ctx.lineTo(x(i), y(v));
        }
      });
      if (started) ctx.stroke();
    }

    drawLine("sma20", "#176b87");
    drawLine("sma50", "#a66a00");

    const first = rows[0]?.date || "";
    const last = rows[rows.length - 1]?.date || "";
    ctx.fillStyle = "#64748b";
    ctx.fillText(`${first} to ${last}`, pad.l, h - 16);
    ctx.fillText(`High ${max.toFixed(2)} / Low ${min.toFixed(2)}`, pad.l, 18);

    const legendY = h - 16;
    [["K", "#2f8f6f"], ["MA20", "#176b87"], ["MA50", "#a66a00"]].forEach((item, idx) => {
      const lx = w - 210 + idx * 66;
      ctx.fillStyle = item[1];
      ctx.fillRect(lx, legendY - 8, 18, 3);
      ctx.fillStyle = "#64748b";
      ctx.fillText(item[0], lx + 24, legendY - 4);
    });

    function fmt(v, digits = 2) {
      const n = Number(v);
      if (!Number.isFinite(n)) return "-";
      return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
    }
    function fmtVol(v) {
      const n = Number(v);
      if (!Number.isFinite(n)) return "-";
      if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
      if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
      if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
      return n.toLocaleString();
    }
    canvas.addEventListener("mousemove", event => {
      const rect = canvas.getBoundingClientRect();
      const mx = (event.clientX - rect.left) * (w / rect.width);
      const my = (event.clientY - rect.top) * (h / rect.height);
      if (mx < pad.l || mx > w - pad.r || my < pad.t || my > h - pad.b || rows.length === 0) {
        tip.style.display = "none";
        return;
      }
      const idx = Math.max(0, Math.min(rows.length - 1, Math.round((mx - pad.l) / Math.max(1, w - pad.l - pad.r) * (rows.length - 1))));
      const r = rows[idx] || {};
      const up = Number(r.close) >= Number(r.open);
      tip.innerHTML = `
        <div style="font-weight:700;margin-bottom:4px;">${r.date || "-"}</div>
        <div>Open <strong>${fmt(r.open)}</strong> &nbsp; High <strong>${fmt(r.high)}</strong></div>
        <div>Low <strong>${fmt(r.low)}</strong> &nbsp; Close <strong style="color:${up ? "#15803d" : "#b91c1c"}">${fmt(r.close)}</strong></div>
        <div>Volume <strong>${fmtVol(r.volume)}</strong></div>
        <div style="color:#64748b;">MA20 ${fmt(r.sma20)} / MA50 ${fmt(r.sma50)}</div>
      `;
      tip.style.display = "block";
      const wrapRect = wrap.getBoundingClientRect();
      const tipWidth = tip.offsetWidth || 188;
      const tipHeight = tip.offsetHeight || 92;
      let left = event.clientX - wrapRect.left + 14;
      let top = event.clientY - wrapRect.top + 14;
      if (left + tipWidth > wrapRect.width - 8) left = event.clientX - wrapRect.left - tipWidth - 14;
      if (top + tipHeight > wrapRect.height - 8) top = event.clientY - wrapRect.top - tipHeight - 14;
      tip.style.left = `${Math.max(8, left)}px`;
      tip.style.top = `${Math.max(8, top)}px`;
    });
    canvas.addEventListener("mouseleave", () => {
      tip.style.display = "none";
    });
    </script>
    """.replace("__DATA__", chart_data)
    components.html(html, height=410)


def render_volume_profile_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>暂无筹码/成交密集区数据。</p>"
    max_vol = max([to_float(r.get("volume")) for r in rows] + [1])
    out = []
    for row in rows[:12]:
        price = to_float(row.get("price"))
        vol = to_float(row.get("volume"))
        width = min(100, max(1, vol / max_vol * 100))
        out.append(
            f'<div class="mini-bar-row"><span>{price:,.2f}</span><div class="mini-track"><div class="mini-fill" style="width:{width:.1f}%"></div></div><span>{vol:,.0f}</span></div>'
        )
    return "".join(out)


def render_options_html(options: dict[str, Any]) -> str:
    if not options.get("available"):
        return f"<p>{clean_text(options.get('note')) or 'No options data.'}</p>"
    summary = options.get("summary", {})
    rows = list(options.get("distribution", []))
    rows.sort(key=lambda r: to_float(r.get("call_oi")) + to_float(r.get("put_oi")), reverse=True)
    max_oi = max([max(to_float(r.get("call_oi")), to_float(r.get("put_oi"))) for r in rows] + [1])
    html = [
        f"<p><strong>Put/Call OI:</strong> {to_float(summary.get('put_call_oi_ratio')):.2f} &nbsp; <strong>Call/Put OI:</strong> {to_float(summary.get('call_put_oi_ratio')):.2f}</p>",
        f"<p><strong>最近到期:</strong> {summary.get('nearest_expiry') or '-'} / 最大 Call OI strike {summary.get('nearest_max_call_oi_strike') or '-'} / 最大 Put OI strike {summary.get('nearest_max_put_oi_strike') or '-'}</p>",
    ]
    for row in rows[:10]:
        strike = to_float(row.get("strike"))
        call_oi = to_float(row.get("call_oi"))
        put_oi = to_float(row.get("put_oi"))
        cw = min(100, max(1, call_oi / max_oi * 100))
        pw = min(100, max(1, put_oi / max_oi * 100))
        html.append(
            f'<div class="mini-bar-row"><span>{strike:,.2f}</span><div class="mini-track"><div class="mini-fill" style="width:{cw:.1f}%"></div></div><span>C {call_oi:,.0f}</span></div>'
            f'<div class="mini-bar-row"><span></span><div class="mini-track"><div class="mini-fill put" style="width:{pw:.1f}%"></div></div><span>P {put_oi:,.0f}</span></div>'
        )
    return "".join(html)


def signed_text(value: Any, percent: bool = True) -> str:
    try:
        num = float(value)
    except Exception:
        return "-"
    return f"{num * 100:+.2f}%" if percent else f"{num:+,.2f}"


def render_index_strip() -> None:
    try:
        data = core.index_overview()
        items = data.get("items", [])
    except Exception as exc:
        st.warning(f"Index data unavailable: {exc}")
        return
    if not items:
        st.info("Index data unavailable.")
        return
    cols = st.columns(min(3, len(items)), gap="medium")
    for col, item in zip(cols, items):
        with col:
            with st.container(border=True):
                name = clean_text(item.get("name")) or "-"
                symbol = clean_text(item.get("symbol")) or "-"
                st.markdown(f"**{name}** `{symbol}`")
                if not item.get("available"):
                    st.warning(clean_text(item.get("comment")) or "No data")
                    continue
                st.metric("Last / 1D", f"{to_float(item.get('last')):,.2f}", signed_text(item.get("day_return")))
                ret_df = pd.DataFrame(
                    [
                        {
                            "5D": signed_text(item.get("return_5d")),
                            "20D": signed_text(item.get("return_20d")),
                            "60D": signed_text(item.get("return_60d")),
                        }
                    ]
                )
                st.dataframe(ret_df, use_container_width=True, hide_index=True, height=70)
                st.caption(f"{clean_text(item.get('trend')) or '-'} | {clean_text(item.get('comment'))}")


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
    st.subheader("Index Tape")
    render_index_strip()
    render_holding_date_alerts(portfolio)

    holdings = pd.DataFrame(portfolio["holdings"])
    if holdings.empty:
        st.warning("No active holdings.")
        return
    st.subheader("Active Holdings")
    holdings = holdings.sort_values("market_value_usd", ascending=False)
    biggest = holdings.iloc[0]
    positive_count = int((holdings["unrealized_pnl_usd"] > 0).sum())
    st.markdown(
        f"""
        <div class="holding-summary">
          <div class="holding-card"><span>Active names</span><strong>{len(holdings)}</strong></div>
          <div class="holding-card"><span>Market value</span><strong>{money(holdings["market_value_usd"].sum())}</strong></div>
          <div class="holding-card"><span>Profitable names</span><strong>{positive_count} / {len(holdings)}</strong></div>
          <div class="holding-card"><span>Largest position</span><strong>{biggest["symbol"]} · {money(biggest["market_value_usd"])}</strong></div>
        </div>
        <div class="section-note">Sorted by market value. RS columns show YTD relative strength versus Nasdaq 100 and S&P 500.</div>
        """,
        unsafe_allow_html=True,
    )
    view = holdings[
        [
            "symbol",
            "quantity",
            "avg_cost",
            "last_price",
            "market_value_usd",
            "unrealized_pnl_usd",
            "unrealized_pct",
            "changes_percentage",
            "return_ytd",
            "rs_vs_nq_ytd",
            "rs_vs_sp_ytd",
        ]
    ].rename(
        columns={
            "symbol": "Symbol",
            "quantity": "Qty",
            "avg_cost": "Avg Cost",
            "last_price": "Last",
            "market_value_usd": "Market Value",
            "unrealized_pnl_usd": "Unrealized",
            "unrealized_pct": "PnL %",
            "changes_percentage": "Day",
            "return_ytd": "YTD",
            "rs_vs_nq_ytd": "RS NQ YTD",
            "rs_vs_sp_ytd": "RS SP YTD",
        }
    )
    styled = view.style.format(
        {
            "Qty": "{:,.0f}",
            "Avg Cost": "{:,.2f}",
            "Last": "{:,.2f}",
            "Market Value": "${:,.0f}",
            "Unrealized": "${:,.0f}",
            "PnL %": "{:+.2%}",
            "Day": "{:+.2f}%",
            "YTD": "{:+.2%}",
            "RS NQ YTD": "{:+.2%}",
            "RS SP YTD": "{:+.2%}",
        },
        na_rep="-",
    )
    signed_cols = ["Unrealized", "PnL %", "Day", "YTD", "RS NQ YTD", "RS SP YTD"]
    if hasattr(styled, "map"):
        styled = styled.map(color_signed, subset=signed_cols)
    else:
        styled = styled.applymap(color_signed, subset=signed_cols)
    styled = (
        styled.set_properties(subset=["Symbol"], **{"font-weight": "700", "color": "#1d4ed8"})
        .set_table_styles(
            [
                {"selector": "th", "props": [("background-color", "#f8fafc"), ("color", "#475569"), ("font-weight", "700")]},
                {"selector": "td", "props": [("border-color", "#e5e7eb")]},
            ]
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True, height=min(560, 42 + 36 * len(view)))


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
    advice = tech.get("advice", {})
    signals = tech.get("signals", [])[:10]
    col_chart, col_side = st.columns([1.35, 0.65], gap="medium")
    with col_chart:
        render_candlestick_chart(tech.get("history", []))
    with col_side:
        st.markdown(
            f"""
            <div class="panel-card">
              <h4>技术点位与操作建议</h4>
              <p><strong>短期：</strong>{clean_text(advice.get("short_term")) or '-'}</p>
              <p><strong>中期：</strong>{clean_text(advice.get("medium_term")) or '-'}</p>
            </div>
            <div class="panel-card">
              <h4>关键技术信息</h4>
              <ul>{''.join(f'<li>{clean_text(x)}</li>' for x in signals) or '<li>-</li>'}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

    left, right = st.columns(2, gap="medium")
    with left:
        st.markdown(
            f"""
            <div class="panel-card">
              <h4>筹码 / 成交密集区</h4>
              {render_volume_profile_html(tech.get("levels", {}).get("volume_profile", []))}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"""
            <div class="panel-card">
              <h4>期权 OI 分布</h4>
              {render_options_html(detail.get("options", {}))}
            </div>
            """,
            unsafe_allow_html=True,
        )

    news = detail.get("news", {})
    sentiment = news.get("sentiment", {})
    items = news.get("items", [])[:10]
    st.markdown(
        f"""
        <div class="panel-card">
          <h4>过去24小时新闻与热度</h4>
          <p><strong>Heat:</strong> {sentiment.get('heat', 0)}/100 &nbsp; <strong>Tone:</strong> {clean_text(sentiment.get('comment')) or 'neutral'}</p>
          <ul>
            {''.join(f'<li><a class="news-link" href="{clean_text(n.get("url"))}" target="_blank">{clean_text(n.get("title")) or "Untitled"}</a><br><span style="color:#64748b;font-size:12px;">{clean_text(n.get("site"))} / {clean_text(n.get("publishedDate"))}</span></li>' for n in items) or '<li>过去24小时没有返回相关新闻。</li>'}
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


MACRO_KEYWORDS = [
    "pce",
    "cpi",
    "ppi",
    "inflation",
    "pmi",
    "ism",
    "unemployment",
    "jobless",
    "claims",
    "payroll",
    "employment",
    "fomc",
    "fed",
    "gdp",
    "retail sales",
    "durable goods",
    "consumer confidence",
    "personal income",
    "personal spending",
]


def macro_priority(event: Any, impact: Any = "") -> str:
    text = f"{event or ''} {impact or ''}".lower()
    if any(word in text for word in ["pce", "cpi", "ppi", "unemployment", "payroll", "fomc", "fed"]):
        return "Hot"
    if any(word in text for word in MACRO_KEYWORDS):
        return "Watch"
    if str(impact or "").lower() == "high":
        return "Hot"
    if str(impact or "").lower() == "medium":
        return "Watch"
    return "Normal"


def macro_priority_style(value: Any) -> str:
    text = str(value).lower()
    if text == "hot":
        return "background-color:#fee2e2;color:#991b1b;font-weight:700"
    if text == "watch":
        return "background-color:#fef3c7;color:#92400e;font-weight:700"
    return "color:#475569"


def style_priority_table(df: pd.DataFrame) -> Any:
    if df.empty or "Priority" not in df.columns:
        return df
    styled = df.style
    if hasattr(styled, "map"):
        return styled.map(macro_priority_style, subset=["Priority"])
    return styled.applymap(macro_priority_style, subset=["Priority"])


def weekly_macro_calendar(days: int = 7) -> list[dict[str, Any]]:
    today = dt.date.today()
    end = today + dt.timedelta(days=days)
    data = core.fmp_get("/stable/economic-calendar", {"from": today.isoformat(), "to": end.isoformat()}, ttl=900)
    if not isinstance(data, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in data:
        event = clean_text(item.get("event") or item.get("name"))
        impact = clean_text(item.get("impact") or item.get("importance"))
        priority = macro_priority(event, impact)
        text = event.lower()
        if priority == "Normal" and not any(word in text for word in MACRO_KEYWORDS):
            continue
        rows.append(
            {
                "Date": clean_text(item.get("date")),
                "Country": clean_text(item.get("country")),
                "Event": event,
                "Priority": priority,
                "Impact": impact or "-",
                "Estimate": clean_text(item.get("estimate") or item.get("consensus")) or "-",
                "Previous": clean_text(item.get("previous")) or "-",
            }
        )
    rows.sort(key=lambda x: (x["Date"], {"Hot": 0, "Watch": 1, "Normal": 2}.get(x["Priority"], 2)))
    return rows[:30]


def portfolio_event_calendar(symbols: list[str], days: int = 45) -> list[dict[str, Any]]:
    wanted = {clean_text(symbol).upper() for symbol in symbols if clean_text(symbol)}
    if not wanted:
        return []
    today = dt.date.today()
    end = today + dt.timedelta(days=days)
    rows: list[dict[str, Any]] = []

    earnings = core.fmp_get("/stable/earnings-calendar", {"from": today.isoformat(), "to": end.isoformat()}, ttl=3600)
    if isinstance(earnings, list):
        for item in earnings:
            symbol = clean_text(item.get("symbol") or item.get("ticker")).upper()
            if symbol not in wanted:
                continue
            eps = compact_number(item.get("epsEstimated") or item.get("epsEstimate"))
            revenue = compact_large_number(item.get("revenueEstimated") or item.get("revenueEstimate"))
            rows.append(
                {
                    "Date": clean_text(item.get("date")) or "-",
                    "Symbol": symbol,
                    "Type": "Earnings",
                    "Detail": f"EPS est {eps} | Revenue est {revenue}",
                }
            )

    dividends = core.fmp_get("/stable/dividends-calendar", {"from": today.isoformat(), "to": end.isoformat()}, ttl=3600)
    if isinstance(dividends, list):
        for item in dividends:
            symbol = clean_text(item.get("symbol") or item.get("ticker")).upper()
            if symbol not in wanted:
                continue
            dividend = compact_number(item.get("dividend") or item.get("adjDividend"))
            rows.append(
                {
                    "Date": clean_text(item.get("date") or item.get("exDividendDate")) or "-",
                    "Symbol": symbol,
                    "Type": "Dividend",
                    "Detail": f"Dividend {dividend} | Record {clean_text(item.get('recordDate')) or '-'} | Pay {clean_text(item.get('paymentDate')) or '-'}",
                }
            )

    rows.sort(key=lambda x: (x["Date"], x["Symbol"], x["Type"]))
    return rows[:40]


def macro_brief_lines(macro: dict[str, Any]) -> list[str]:
    lines = [clean_text(line) for line in macro.get("analysis", []) if clean_text(line)]
    if lines:
        return lines[:4]
    items = macro.get("items", [])[:4]
    out = []
    for item in items:
        actual = clean_text(item.get("actual")) or "-"
        estimate = clean_text(item.get("estimate")) or "-"
        out.append(f"{clean_text(item.get('event'))}: actual {actual}, estimate {estimate}.")
    return out or ["-"]


def operation_notes(index_items: list[dict[str, Any]], macro: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    weak_indexes = [
        clean_text(item.get("name"))
        for item in index_items
        if to_float(item.get("return_20d")) < 0 and clean_text(item.get("name"))
    ]
    hot_macro = [
        item
        for item in macro.get("items", [])
        if macro_priority(item.get("event"), item.get("impact") or item.get("importance")) == "Hot"
    ]
    if weak_indexes:
        notes.append(f"指数短期仍偏谨慎：{', '.join(weak_indexes[:3])} 20D 回报为负，组合追高要更挑相对强势标的。")
    else:
        notes.append("指数短期没有明显系统性破坏，持仓可以继续按个股强弱和事件节奏管理。")
    if hot_macro:
        notes.append("本周和过去 24h 有通胀、就业或 Fed 类关键数据，建议控制高 beta 仓位的隔夜波动风险。")
    notes.append("操作上优先保留 YTD 相对 NQ/SP 仍强的持仓；跌破关键均线且相对强弱转负的名字，先降低仓位或等待确认。")
    return notes


def render_macro_indexes(portfolio: dict[str, Any]) -> None:
    st.subheader("Macro Brief")
    try:
        macro = core.macro_updates()
    except Exception as exc:
        st.error(str(exc))
        macro = {"analysis": [], "items": []}
    try:
        idx = core.index_overview()
        index_items = idx.get("items", [])
    except Exception as exc:
        st.error(str(exc))
        index_items = []

    top_left, top_right = st.columns([1.15, 0.85], gap="medium")
    with top_left:
        with st.container(border=True):
            st.markdown("**上一交易日宏观重点**")
            for line in macro_brief_lines(macro):
                st.write(f"- {line}")
    with top_right:
        with st.container(border=True):
            st.markdown("**对组合操作的含义**")
            for line in operation_notes(index_items, macro):
                st.write(f"- {line}")

    cal_left, cal_right = st.columns(2, gap="medium")
    with cal_left:
        st.markdown("#### This Week Macro Calendar")
        macro_calendar = pd.DataFrame(weekly_macro_calendar())
        if macro_calendar.empty:
            st.info("-")
        else:
            st.dataframe(style_priority_table(macro_calendar), use_container_width=True, hide_index=True, height=min(420, 42 + 34 * len(macro_calendar)))
    with cal_right:
        st.markdown("#### Holding Date Alerts")
        symbols = [p["symbol"] for p in portfolio.get("holdings", [])]
        events = pd.DataFrame(portfolio_event_calendar(symbols))
        if events.empty:
            st.info("-")
        else:
            st.dataframe(events, use_container_width=True, hide_index=True, height=min(420, 42 + 34 * len(events)))

    idx_df = pd.DataFrame(index_items)
    st.markdown("#### Index Snapshot")
    if idx_df.empty:
        st.info("-")
    else:
        cols = ["name", "last", "day_return", "return_5d", "return_20d", "return_60d", "trend", "comment"]
        existing = [col for col in cols if col in idx_df.columns]
        view = idx_df[existing].rename(
            columns={
                "name": "Index",
                "last": "Last",
                "day_return": "Day",
                "return_5d": "5D",
                "return_20d": "20D",
                "return_60d": "60D",
                "trend": "Trend",
                "comment": "Comment",
            }
        )
        st.dataframe(view, use_container_width=True, hide_index=True)

    st.markdown("#### 24h Macro Tape")
    rows = pd.DataFrame(macro.get("items", []))
    if rows.empty:
        st.info("-")
    else:
        rows["Priority"] = rows.apply(lambda row: macro_priority(row.get("event"), row.get("impact") or row.get("importance")), axis=1)
        cols = ["date", "country", "event", "Priority", "impact", "actual", "estimate", "previous", "category", "comment"]
        existing = [col for col in cols if col in rows.columns]
        view = rows[existing].rename(
            columns={
                "date": "Date",
                "country": "Country",
                "event": "Event",
                "impact": "Impact",
                "actual": "Actual",
                "estimate": "Estimate",
                "previous": "Previous",
                "category": "Category",
                "comment": "Comment",
            }
        )
        st.dataframe(style_priority_table(view), use_container_width=True, hide_index=True)


def macro_cell(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return "-"
    try:
        float(text.replace(",", ""))
    except Exception:
        return text
    return compact_number(text)


def render_macro_card(title: str, lines: list[str]) -> None:
    bullets = "".join(f"<li>{safe_html(line)}</li>" for line in lines if clean_text(line)) or "<li>-</li>"
    st.markdown(
        f"""
<div class="macro-brief-card">
  <h4>{safe_html(title)}</h4>
  <ul>{bullets}</ul>
</div>
""",
        unsafe_allow_html=True,
    )


def operation_notes(index_items: list[dict[str, Any]], macro: dict[str, Any]) -> list[str]:
    weak_indexes = [
        clean_text(item.get("name"))
        for item in index_items
        if to_float(item.get("return_20d")) < 0 and clean_text(item.get("name"))
    ]
    hot_macro = [
        item
        for item in macro.get("items", [])
        if macro_priority(item.get("event"), item.get("impact") or item.get("importance")) == "Hot"
    ]
    notes: list[str] = []
    if weak_indexes:
        notes.append(f"指数短期仍偏谨慎：{', '.join(weak_indexes[:3])} 20D 回报为负，追高要更挑相对强势标的。")
    else:
        notes.append("指数短期没有明显系统性破坏，持仓可以继续按个股强弱和事件节奏管理。")
    if hot_macro:
        notes.append("本周和过去 24h 有通胀、就业或 Fed 类关键数据，建议控制高 beta 仓位的隔夜波动风险。")
    notes.append("操作上优先保留 YTD 相对 NQ/SP 仍强的持仓；相对强弱转负且跌破关键均线的名字，先降低仓位或等待确认。")
    return notes


def render_holding_date_alerts(portfolio: dict[str, Any]) -> None:
    st.subheader("Holding Date Alerts")
    symbols = [p["symbol"] for p in portfolio.get("holdings", [])]
    events = pd.DataFrame(portfolio_event_calendar(symbols))
    if events.empty:
        st.info("-")
        return
    st.dataframe(
        events,
        use_container_width=True,
        hide_index=True,
        height=min(260, 42 + 34 * len(events)),
        column_config={
            "Date": st.column_config.TextColumn("Date", width="small"),
            "Symbol": st.column_config.TextColumn("Symbol", width="small"),
            "Type": st.column_config.TextColumn("Type", width="small"),
            "Detail": st.column_config.TextColumn("Detail", width="large"),
        },
    )


def render_macro_indexes(portfolio: dict[str, Any]) -> None:
    st.subheader("Macro Brief")
    try:
        macro = core.macro_updates()
    except Exception as exc:
        st.error(str(exc))
        macro = {"analysis": [], "items": []}
    try:
        idx = core.index_overview()
        index_items = idx.get("items", [])
    except Exception as exc:
        st.error(str(exc))
        index_items = []

    top_left, top_right = st.columns([1.15, 0.85], gap="medium")
    with top_left:
        render_macro_card("上一交易日宏观重点", macro_brief_lines(macro))
    with top_right:
        render_macro_card("对组合操作的含义", operation_notes(index_items, macro))

    cal_left, cal_right = st.columns(2, gap="medium")
    with cal_left:
        st.markdown("#### This Week Macro Calendar")
        macro_calendar = pd.DataFrame(weekly_macro_calendar())
        if macro_calendar.empty:
            st.info("-")
        else:
            for col in ["Estimate", "Previous"]:
                if col in macro_calendar.columns:
                    macro_calendar[col] = macro_calendar[col].apply(macro_cell)
            st.dataframe(
                style_priority_table(macro_calendar),
                use_container_width=True,
                hide_index=True,
                height=min(420, 42 + 34 * len(macro_calendar)),
                column_config={
                    "Date": st.column_config.TextColumn("Date", width="small"),
                    "Country": st.column_config.TextColumn("Country", width="small"),
                    "Event": st.column_config.TextColumn("Event", width="large"),
                    "Priority": st.column_config.TextColumn("Priority", width="small"),
                    "Impact": st.column_config.TextColumn("Impact", width="small"),
                    "Estimate": st.column_config.TextColumn("Estimate", width="small"),
                    "Previous": st.column_config.TextColumn("Previous", width="small"),
                },
            )
    with cal_right:
        render_holding_date_alerts(portfolio)

    idx_df = pd.DataFrame(index_items)
    st.markdown("#### Index Snapshot")
    if idx_df.empty:
        st.info("-")
    else:
        cols = ["name", "last", "day_return", "return_5d", "return_20d", "return_60d", "trend", "comment"]
        existing = [col for col in cols if col in idx_df.columns]
        view = idx_df[existing].rename(
            columns={
                "name": "Index",
                "last": "Last",
                "day_return": "Day",
                "return_5d": "5D",
                "return_20d": "20D",
                "return_60d": "60D",
                "trend": "Trend",
                "comment": "Comment",
            }
        )
        for col in ["Day", "5D", "20D", "60D"]:
            if col in view.columns:
                view[col] = view[col].apply(compact_pct)
        if "Last" in view.columns:
            view["Last"] = view["Last"].apply(lambda x: compact_number(x, 2))
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            height=150,
            column_config={
                "Index": st.column_config.TextColumn("Index", width="small"),
                "Last": st.column_config.TextColumn("Last", width="small"),
                "Day": st.column_config.TextColumn("Day", width="small"),
                "5D": st.column_config.TextColumn("5D", width="small"),
                "20D": st.column_config.TextColumn("20D", width="small"),
                "60D": st.column_config.TextColumn("60D", width="small"),
                "Trend": st.column_config.TextColumn("Trend", width="small"),
                "Comment": st.column_config.TextColumn("Comment", width="large"),
            },
        )

    st.markdown("#### 24h Macro Tape")
    rows = pd.DataFrame(macro.get("items", []))
    if rows.empty:
        st.info("-")
    else:
        rows["Priority"] = rows.apply(lambda row: macro_priority(row.get("event"), row.get("impact") or row.get("importance")), axis=1)
        cols = ["date", "country", "event", "Priority", "actual", "estimate", "previous", "category", "comment"]
        existing = [col for col in cols if col in rows.columns]
        view = rows[existing].rename(
            columns={
                "date": "Date",
                "country": "Country",
                "event": "Event",
                "actual": "Actual",
                "estimate": "Estimate",
                "previous": "Previous",
                "category": "Category",
                "comment": "Comment",
            }
        )
        for col in ["Actual", "Estimate", "Previous"]:
            if col in view.columns:
                view[col] = view[col].apply(macro_cell)
        st.dataframe(
            style_priority_table(view),
            use_container_width=True,
            hide_index=True,
            height=min(520, 42 + 34 * len(view)),
            column_config={
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Country": st.column_config.TextColumn("Country", width="small"),
                "Event": st.column_config.TextColumn("Event", width="medium"),
                "Priority": st.column_config.TextColumn("Priority", width="small"),
                "Actual": st.column_config.TextColumn("Actual", width="small"),
                "Estimate": st.column_config.TextColumn("Estimate", width="small"),
                "Previous": st.column_config.TextColumn("Previous", width="small"),
                "Category": st.column_config.TextColumn("Category", width="small"),
                "Comment": st.column_config.TextColumn("Comment", width="large"),
            },
    )


@st.cache_data(ttl=900, show_spinner=False)
def risk_history(symbols: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    return {symbol: core.historical_prices(symbol) for symbol in symbols}


def returns_from_history(rows: list[dict[str, Any]], suffix: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", suffix])
    frame = pd.DataFrame(rows)
    if "date" not in frame.columns or "close" not in frame.columns:
        return pd.DataFrame(columns=["date", suffix])
    frame = frame[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna().sort_values("date")
    frame[suffix] = frame["close"].pct_change()
    return frame[["date", suffix]].dropna()


def max_drawdown(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    wealth = (1 + series.fillna(0)).cumprod()
    peak = wealth.cummax()
    drawdown = wealth / peak - 1
    return float(drawdown.min()) if not drawdown.empty else 0.0


def risk_band(score: float) -> str:
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def percent_text(value: Any, digits: int = 1) -> str:
    try:
        num = float(value)
    except Exception:
        return "-"
    return f"{num * 100:.{digits}f}%"


def risk_bar_chart(data: pd.DataFrame, value_col: str, value_title: str) -> alt.Chart:
    frame = data.copy()
    frame["Label"] = frame[value_col].apply(lambda x: percent_text(x, 1))
    chart_height = max(360, min(680, 42 * len(frame) + 80))
    base = alt.Chart(frame).encode(
        y=alt.Y("Symbol:N", sort="-x", title=None, axis=alt.Axis(labelLimit=140, labelPadding=8)),
        tooltip=[
            alt.Tooltip("Symbol:N", title="Stock"),
            alt.Tooltip(f"{value_col}:Q", title=value_title, format=".2%"),
        ],
    )
    bars = base.mark_bar(cornerRadiusEnd=4, opacity=0.88).encode(
        x=alt.X(f"{value_col}:Q", title=value_title, axis=alt.Axis(format="%")),
        color=alt.Color("Symbol:N", legend=alt.Legend(title="Stock", orient="bottom", columns=6)),
    )
    labels = base.mark_text(align="left", dx=5, color="#334155", fontSize=11).encode(
        x=alt.X(f"{value_col}:Q"),
        text="Label:N",
    )
    return (bars + labels).properties(height=chart_height)


def risk_scatter_chart(scatter: pd.DataFrame) -> alt.Chart:
    frame = scatter.copy()
    frame["Weight Label"] = frame["Weight"].apply(lambda x: percent_text(x, 1))
    frame["Vol Label"] = frame["Annual Vol"].apply(lambda x: percent_text(x, 1))
    frame["Risk Contribution Label"] = frame["Risk Contribution"].apply(lambda x: percent_text(x, 1))
    points = alt.Chart(frame).mark_circle(opacity=0.82, stroke="#ffffff", strokeWidth=1.2).encode(
        x=alt.X("Weight:Q", title="Weight", axis=alt.Axis(format="%")),
        y=alt.Y("Annual Vol:Q", title="Annual Vol", axis=alt.Axis(format="%")),
        size=alt.Size("Risk Contribution:Q", title="Risk Contribution", scale=alt.Scale(range=[80, 850])),
        color=alt.Color("Symbol:N", legend=alt.Legend(title="Stock", orient="bottom", columns=8)),
        tooltip=[
            alt.Tooltip("Symbol:N", title="Stock"),
            alt.Tooltip("Weight:Q", title="Weight", format=".2%"),
            alt.Tooltip("Annual Vol:Q", title="Annual Vol", format=".2%"),
            alt.Tooltip("Beta:Q", title="Beta", format=".2f"),
            alt.Tooltip("Risk Contribution:Q", title="Risk Contribution", format=".2%"),
        ],
    )
    labels = alt.Chart(frame).mark_text(align="left", dx=8, dy=-6, fontSize=11, fontWeight="bold").encode(
        x=alt.X("Weight:Q"),
        y=alt.Y("Annual Vol:Q"),
        text="Symbol:N",
        color=alt.Color("Symbol:N", legend=None),
    )
    return (points + labels).properties(height=500)


def correlation_heatmap(corr: pd.DataFrame) -> alt.Chart:
    frame = corr.reset_index().melt(id_vars="index", var_name="Column", value_name="Correlation")
    frame = frame.rename(columns={"index": "Row"})
    chart_height = max(520, min(900, 42 * len(corr) + 120))
    heat = alt.Chart(frame).mark_rect(cornerRadius=2).encode(
        x=alt.X("Column:N", title=None, axis=alt.Axis(labelAngle=0, labelLimit=120, labelPadding=8)),
        y=alt.Y("Row:N", title=None, axis=alt.Axis(labelLimit=140, labelPadding=8)),
        color=alt.Color(
            "Correlation:Q",
            title="Correlation",
            scale=alt.Scale(domain=[-1, 0, 1], range=["#b91c1c", "#f8fafc", "#15803d"]),
        ),
        tooltip=[
            alt.Tooltip("Row:N", title="Stock A"),
            alt.Tooltip("Column:N", title="Stock B"),
            alt.Tooltip("Correlation:Q", title="Correlation", format=".2f"),
        ],
    )
    text = alt.Chart(frame).mark_text(fontSize=11, color="#0f172a").encode(
        x=alt.X("Column:N"),
        y=alt.Y("Row:N"),
        text=alt.Text("Correlation:Q", format=".2f"),
    )
    return (heat + text).properties(height=chart_height)


def build_risk_assessment(portfolio: dict[str, Any]) -> dict[str, Any]:
    holdings = pd.DataFrame(portfolio.get("holdings", []))
    if holdings.empty:
        return {"ok": False, "note": "No active holdings."}
    holdings = holdings.copy()
    holdings["weight"] = holdings["market_value_usd"] / max(1, holdings["market_value_usd"].sum())
    symbols = tuple(sorted(holdings["symbol"].astype(str).unique()))
    histories = risk_history(symbols + ("^GSPC", "^NDX"))

    merged: pd.DataFrame | None = None
    for symbol in symbols:
        ret = returns_from_history(histories.get(symbol, []), symbol)
        merged = ret if merged is None else merged.merge(ret, on="date", how="inner")
    if merged is None or merged.empty:
        return {"ok": False, "note": "Not enough price history for risk calculation."}
    returns = merged.set_index("date").tail(180)
    available_symbols = [symbol for symbol in symbols if symbol in returns.columns]
    holdings = holdings[holdings["symbol"].isin(available_symbols)].copy()
    if holdings.empty:
        return {"ok": False, "note": "Not enough live holdings with price history."}
    holdings["weight"] = holdings["market_value_usd"] / max(1, holdings["market_value_usd"].sum())
    weight_series = holdings.set_index("symbol")["weight"].reindex(available_symbols).fillna(0)
    weights = weight_series.to_numpy(dtype=float)
    returns = returns[available_symbols].dropna()
    if returns.empty:
        return {"ok": False, "note": "Not enough overlapping price history for risk calculation."}

    portfolio_returns = returns.dot(weights)
    nav = float(portfolio["account"].get("equity_usd") or holdings["market_value_usd"].sum())
    mv = float(holdings["market_value_usd"].sum())
    daily_vol = float(portfolio_returns.std(ddof=1) or 0)
    daily_vol = 0.0 if pd.isna(daily_vol) else daily_vol
    annual_vol = daily_vol * np.sqrt(252)
    var_95 = max(0.0, -float(portfolio_returns.quantile(0.05)))
    tail = portfolio_returns[portfolio_returns <= portfolio_returns.quantile(0.05)]
    cvar_95 = max(0.0, -float(tail.mean())) if not tail.empty else var_95
    mdd = max_drawdown(portfolio_returns)

    sp = returns_from_history(histories.get("^GSPC", []), "SPX")
    nq = returns_from_history(histories.get("^NDX", []), "NDX")
    benchmark = returns.reset_index().merge(sp, on="date", how="inner").merge(nq, on="date", how="inner")
    betas: dict[str, float | None] = {}
    corr_sp: dict[str, float | None] = {}
    corr_nq: dict[str, float | None] = {}
    for symbol in available_symbols:
        if benchmark.empty:
            betas[symbol] = None
            corr_sp[symbol] = None
            corr_nq[symbol] = None
            continue
        var_sp = float(benchmark["SPX"].var(ddof=1) or 0)
        betas[symbol] = float(benchmark[[symbol, "SPX"]].cov().iloc[0, 1] / var_sp) if var_sp else None
        corr_sp[symbol] = float(benchmark[symbol].corr(benchmark["SPX"]))
        corr_nq[symbol] = float(benchmark[symbol].corr(benchmark["NDX"]))
    holdings["beta_sp"] = holdings["symbol"].map(betas)
    holdings["corr_sp"] = holdings["symbol"].map(corr_sp)
    holdings["corr_nq"] = holdings["symbol"].map(corr_nq)
    holdings["ann_vol"] = holdings["symbol"].map(lambda s: float(returns[s].std(ddof=1) * np.sqrt(252)) if s in returns else np.nan)

    cov = returns.cov().to_numpy(dtype=float)
    port_var = float(weights.T @ cov @ weights) if len(weights) else 0.0
    if port_var > 0:
        marginal = cov @ weights
        contribution = weights * marginal / port_var
    else:
        contribution = np.zeros_like(weights)
    risk_contrib = pd.DataFrame({"Symbol": available_symbols, "Risk Contribution": contribution})
    holdings = holdings.merge(risk_contrib, left_on="symbol", right_on="Symbol", how="left").drop(columns=["Symbol"])

    hhi = float((holdings["weight"] ** 2).sum())
    effective_names = 1 / hhi if hhi else 0
    top1 = float(holdings["weight"].max())
    top3 = float(holdings.sort_values("weight", ascending=False)["weight"].head(3).sum())
    weighted_beta = float((holdings["weight"] * holdings["beta_sp"].fillna(1.0)).sum())
    avg_corr = float(returns.corr().where(~np.eye(len(available_symbols), dtype=bool)).stack().mean()) if len(available_symbols) > 1 else 1.0
    weighted_beta = 1.0 if pd.isna(weighted_beta) else weighted_beta
    avg_corr = 0.0 if pd.isna(avg_corr) else avg_corr

    score = 0.0
    score += min(25, annual_vol / 0.35 * 25)
    score += min(20, var_95 / 0.025 * 20)
    score += min(20, top1 / 0.30 * 20)
    score += min(15, max(0, weighted_beta - 0.8) / 0.8 * 15)
    score += min(10, max(0, avg_corr - 0.35) / 0.45 * 10)
    score += min(10, max(0, -mdd) / 0.25 * 10)

    recommendations: list[str] = []
    if top1 > 0.25:
        name = holdings.sort_values("weight", ascending=False).iloc[0]["symbol"]
        recommendations.append(f"{name} 单票权重 {top1:.1%}，已进入集中度警戒区；建议设定减仓/保护触发线，或把新增资金优先分配给低相关持仓。")
    if effective_names < 6:
        recommendations.append(f"有效持仓数只有 {effective_names:.1f}，组合看起来比名义持仓更集中；建议用单票上限和行业/主题上限约束。")
    if weighted_beta > 1.2:
        recommendations.append(f"组合对 S&P 500 的加权 beta 约 {weighted_beta:.2f}，市场回撤时组合会放大波动；建议用指数仓位/现金/低 beta 持仓降低净 beta。")
    if annual_vol > 0.30:
        recommendations.append(f"组合年化波动约 {annual_vol:.1%}，属于高波动组合；建议用 1D VaR 和最大回撤阈值作为强制复盘触发。")
    if avg_corr > 0.65:
        recommendations.append(f"持仓平均相关性约 {avg_corr:.2f}，分散化效果有限；压力情景下相关性可能进一步上升。")
    if not recommendations:
        recommendations.append("当前量化风险指标没有触发高强度警戒；建议继续监控单票权重、beta、VaR 和相关性是否恶化。")

    scenarios = pd.DataFrame(
        [
            {"Scenario": "S&P -3%", "Assumption": "Beta-adjusted market shock", "Estimated PnL": -mv * weighted_beta * 0.03, "Pct NAV": -mv * weighted_beta * 0.03 / nav},
            {"Scenario": "S&P -5%", "Assumption": "Beta-adjusted market shock", "Estimated PnL": -mv * weighted_beta * 0.05, "Pct NAV": -mv * weighted_beta * 0.05 / nav},
            {"Scenario": "S&P -10%", "Assumption": "Stress market shock", "Estimated PnL": -mv * weighted_beta * 0.10, "Pct NAV": -mv * weighted_beta * 0.10 / nav},
            {"Scenario": "Largest name -15%", "Assumption": "Single-name gap on largest position", "Estimated PnL": -mv * top1 * 0.15, "Pct NAV": -mv * top1 * 0.15 / nav},
            {"Scenario": "Historical 1D VaR 95%", "Assumption": "Past daily return distribution", "Estimated PnL": -nav * var_95, "Pct NAV": -var_95},
        ]
    )
    return {
        "ok": True,
        "holdings": holdings,
        "returns": returns,
        "portfolio_returns": portfolio_returns,
        "risk_contrib": risk_contrib,
        "scenarios": scenarios,
        "metrics": {
            "nav": nav,
            "market_value": mv,
            "risk_score": min(100, score),
            "risk_band": risk_band(score),
            "annual_vol": annual_vol,
            "var_95": var_95,
            "cvar_95": cvar_95,
            "max_drawdown": mdd,
            "top1": top1,
            "top3": top3,
            "effective_names": effective_names,
            "weighted_beta": weighted_beta,
            "avg_corr": avg_corr,
        },
        "recommendations": recommendations,
    }


def render_risk_assessment(portfolio: dict[str, Any]) -> None:
    st.subheader("Risk Assessment")
    risk = build_risk_assessment(portfolio)
    if not risk.get("ok"):
        st.info(risk.get("note", "-"))
        return
    metrics = risk["metrics"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risk Score", f"{metrics['risk_score']:.0f}/100", metrics["risk_band"])
    c2.metric("Annualized Vol", pct(metrics["annual_vol"]))
    c3.metric("1D VaR 95%", money(-metrics["nav"] * metrics["var_95"]), pct(-metrics["var_95"]))
    c4.metric("Weighted Beta", f"{metrics['weighted_beta']:.2f}")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("CVaR 95%", money(-metrics["nav"] * metrics["cvar_95"]), pct(-metrics["cvar_95"]))
    c6.metric("Max Drawdown", pct(metrics["max_drawdown"]))
    c7.metric("Top 3 Weight", pct(metrics["top3"]))
    c8.metric("Effective Names", f"{metrics['effective_names']:.1f}")

    st.markdown("#### Risk Manager View")
    for item in risk["recommendations"]:
        st.write(f"- {item}")
    st.caption("口径：基于当前持仓 market value 权重与最近约 180 个交易日历史收益。结果是风控筛查，不是正式交易指令。")

    holdings = risk["holdings"].sort_values("weight", ascending=False).copy()
    chart_left, chart_right = st.columns(2, gap="medium")
    with chart_left:
        st.markdown("#### Position Weight")
        alloc = holdings[["symbol", "weight"]].rename(columns={"symbol": "Symbol", "weight": "Weight"})
        st.altair_chart(risk_bar_chart(alloc, "Weight", "Position Weight"), use_container_width=True)
    with chart_right:
        st.markdown("#### Risk Contribution")
        rc = holdings[["symbol", "Risk Contribution"]].rename(columns={"symbol": "Symbol"})
        rc["Risk Contribution"] = pd.to_numeric(rc["Risk Contribution"], errors="coerce").fillna(0)
        st.altair_chart(risk_bar_chart(rc, "Risk Contribution", "Risk Contribution"), use_container_width=True)

    scatter = holdings[["symbol", "weight", "ann_vol", "beta_sp", "Risk Contribution"]].rename(
        columns={"symbol": "Symbol", "weight": "Weight", "ann_vol": "Annual Vol", "beta_sp": "Beta", "Risk Contribution": "Risk Contribution"}
    )
    scatter["Risk Contribution"] = pd.to_numeric(scatter["Risk Contribution"], errors="coerce").abs().fillna(0.001).clip(lower=0.001)
    scatter["Annual Vol"] = pd.to_numeric(scatter["Annual Vol"], errors="coerce").fillna(0)
    scatter["Beta"] = pd.to_numeric(scatter["Beta"], errors="coerce").fillna(1)
    st.markdown("#### Weight vs Volatility")
    st.altair_chart(risk_scatter_chart(scatter), use_container_width=True)

    detail = holdings[
        ["symbol", "market_value_usd", "weight", "ann_vol", "beta_sp", "corr_sp", "corr_nq", "Risk Contribution", "unrealized_pnl_usd"]
    ].rename(
        columns={
            "symbol": "Symbol",
            "market_value_usd": "Market Value",
            "weight": "Weight",
            "ann_vol": "Annual Vol",
            "beta_sp": "Beta SPX",
            "corr_sp": "Corr SPX",
            "corr_nq": "Corr NDX",
            "Risk Contribution": "Risk Contribution",
            "unrealized_pnl_usd": "Unrealized",
        }
    )
    styled = detail.style.format(
        {
            "Market Value": "${:,.0f}",
            "Weight": "{:.2%}",
            "Annual Vol": "{:.2%}",
            "Beta SPX": "{:.2f}",
            "Corr SPX": "{:.2f}",
            "Corr NDX": "{:.2f}",
            "Risk Contribution": "{:.2%}",
            "Unrealized": "${:,.0f}",
        },
        na_rep="-",
    )
    if hasattr(styled, "map"):
        styled = styled.map(color_signed, subset=["Unrealized"])
    else:
        styled = styled.applymap(color_signed, subset=["Unrealized"])
    st.markdown("#### Position Risk Table")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=min(520, 42 + 34 * len(detail)))

    scenario = risk["scenarios"].copy()
    scenario_view = scenario.style.format({"Estimated PnL": "${:,.0f}", "Pct NAV": "{:+.2%}"})
    if hasattr(scenario_view, "map"):
        scenario_view = scenario_view.map(color_signed, subset=["Estimated PnL", "Pct NAV"])
    else:
        scenario_view = scenario_view.applymap(color_signed, subset=["Estimated PnL", "Pct NAV"])
    st.markdown("#### Stress Scenarios")
    st.dataframe(scenario_view, use_container_width=True, hide_index=True, height=245)

    if len(risk["returns"].columns) > 1:
        st.markdown("#### Correlation Matrix")
        corr = risk["returns"].corr().round(2)
        st.altair_chart(correlation_heatmap(corr), use_container_width=True)


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
    inject_styles()
    role, user = login_gate()
    st.title("Equity PnL Monitor")
    if not cloud_ledger_enabled():
        st.warning("Cloud ledger is not configured. This run uses local fallback data; sharing needs Apps Script or Google Sheets secrets.")
    trades = load_trades()
    portfolio = compute_portfolio_from_trades(trades)
    tabs = st.tabs(["Overview", "Trade Entry", "Stock Detail", "Risk Assessment", "Indexes & Macro", "Records"])
    with tabs[0]:
        render_overview(portfolio)
    with tabs[1]:
        render_trade_entry(role, user)
    with tabs[2]:
        render_stock_detail(portfolio)
    with tabs[3]:
        render_risk_assessment(portfolio)
    with tabs[4]:
        render_macro_indexes(portfolio)
    with tabs[5]:
        render_admin(role, portfolio)


if __name__ == "__main__":
    main()
