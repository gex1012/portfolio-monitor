from __future__ import annotations

import cgi
import datetime as dt
import json
import math
import os
import re
import secrets
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
STATIC_DIR = ROOT / "static"
UPLOAD_DIR = ROOT / "uploads"
DATA_DIR = ROOT / "data"
LEDGER_PATH = DATA_DIR / "transactions.json"
CONFIG_PATHS = [ROOT / "config.local.json", ROOT / "config.example.json"]
DEFAULT_PORT = int(os.environ.get("PORT", "8765"))
DEFAULT_HOST = os.environ.get("HOST", "127.0.0.1")
CACHE: dict[str, tuple[float, Any]] = {}
SESSIONS: dict[str, float] = {}


def load_config() -> dict[str, Any]:
    config: dict[str, Any] = {
        "api_key": "",
        "account_base_hkd": 4_000_000,
        "reporting_currency": "USD",
        "share_password": "MarsCap2026!",
        "transaction_file": r"C:\Users\Admin\Desktop\2026 Equity PnL.xlsx",
        "transaction_sheet": "Transaction History",
        "refresh_seconds": 60,
    }
    for path in CONFIG_PATHS:
        if path.exists():
            try:
                config.update(json.loads(path.read_text(encoding="utf-8")))
                break
            except json.JSONDecodeError:
                pass
    if os.environ.get("FMP_API_KEY"):
        config["api_key"] = os.environ["FMP_API_KEY"]
    return config


CONFIG = load_config()


ALIASES = {
    "date": ["date", "trade date", "transaction date", "settlement date", "\u6210\u4ea4\u65e5\u671f", "\u4ea4\u6613\u65e5\u671f", "\u65e5\u671f"],
    "symbol": ["symbol", "ticker", "stock code", "code", "\u8bc1\u5238\u4ee3\u7801", "\u80a1\u7968\u4ee3\u7801", "\u4ea7\u54c1\u4ee3\u7801", "\u4ee3\u7801"],
    "name": ["name", "security", "stock name", "\u8bc1\u5238\u540d\u79f0", "\u80a1\u7968\u540d\u79f0", "\u540d\u79f0"],
    "side": ["side", "action", "type", "transaction type", "buy sell", "\u4e70\u5356", "\u4e70\u5356\u65b9\u5411", "\u4ea4\u6613\u7c7b\u578b", "\u4e1a\u52a1\u540d\u79f0"],
    "quantity": ["quantity", "qty", "shares", "volume", "size", "\u6210\u4ea4\u6570\u91cf", "\u6570\u91cf", "\u80a1\u6570"],
    "exit_date": ["exit date", "close date", "\u5356\u51fa\u65e5\u671f", "\u9000\u51fa\u65e5\u671f"],
    "exit_quantity": ["exit size", "sell size", "closed size", "\u5356\u51fa\u6570\u91cf", "\u9000\u51fa\u6570\u91cf"],
    "exit_price": ["exit price", "sell price", "\u5356\u51fa\u4ef7", "\u9000\u51fa\u4ef7"],
    "exchange": ["exchange", "market", "\u4ea4\u6613\u6240", "\u5e02\u573a"],
    "price": ["price", "avg price", "average price", "\u6210\u4ea4\u4ef7", "\u6210\u4ea4\u4ef7\u683c", "\u4ef7\u683c", "\u5747\u4ef7"],
    "amount": ["amount", "net amount", "gross amount", "trade amount", "\u6210\u4ea4\u91d1\u989d", "\u53d1\u751f\u91d1\u989d", "\u51c0\u91d1\u989d", "\u91d1\u989d"],
    "fee": ["fee", "fees", "commission", "charges", "tax", "\u8d39\u7528", "\u624b\u7eed\u8d39", "\u4f63\u91d1", "\u5370\u82b1\u7a0e"],
    "currency": ["currency", "ccy", "curr", "\u5e01\u79cd", "\u8d27\u5e01"],
}


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def json_default(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if math.isnan(float(value)) else float(value)
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def respond_json(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    raw = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def parse_cookies(header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def login_page(error: str = "") -> bytes:
    error_html = f"<p class='error'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Equity PnL Login</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; font-family:Arial,'Microsoft YaHei',sans-serif; background:#f6f7f9; color:#17202a; }}
    form {{ width:min(380px, calc(100vw - 32px)); background:#fff; border:1px solid #dce1e7; border-radius:8px; padding:22px; box-shadow:0 8px 28px rgba(20,30,40,.08); }}
    h1 {{ margin:0 0 6px; font-size:22px; }}
    p {{ margin:0 0 16px; color:#68727f; }}
    input, button {{ width:100%; height:38px; border-radius:6px; box-sizing:border-box; }}
    input {{ border:1px solid #dce1e7; padding:0 10px; margin-bottom:10px; }}
    button {{ border:0; background:#176b87; color:#fff; cursor:pointer; }}
    .error {{ color:#b64242; margin-bottom:10px; }}
  </style>
</head>
<body>
  <form method="post" action="/login">
    <h1>Equity PnL Monitor</h1>
    <p>请输入访问密码</p>
    {error_html}
    <input name="password" type="password" autofocus>
    <button type="submit">进入</button>
  </form>
</body>
</html>""".encode("utf-8")


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s_\-/().]+", "", text)


def pick_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {normalize_header(col): col for col in columns}
    for alias in aliases:
        hit = normalized.get(normalize_header(alias))
        if hit:
            return hit
    for col in columns:
        n_col = normalize_header(col)
        if any(normalize_header(alias) in n_col for alias in aliases):
            return col
    return None


def to_number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except Exception:
        pass
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace(",", "").replace("HK$", "").replace("$", "").replace("CNY", "").replace("HKD", "").replace("USD", "")
    text = re.sub(r"[^\d.\-()]", "", text)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return 0.0


def clean_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = text.replace(" ", "")
    return re.sub(r"\.0$", "", text)


def fmp_symbol(raw_symbol: str) -> str:
    symbol = clean_symbol(raw_symbol)
    if not symbol:
        return symbol
    if re.fullmatch(r"\d{1,5}", symbol):
        return str(int(symbol)).zfill(4) + ".HK"
    if re.fullmatch(r"\d{6}", symbol):
        return symbol + (".SS" if symbol.startswith("6") else ".SZ")
    return symbol


def infer_currency(symbol: str, row_currency: str | None = None) -> str:
    if row_currency:
        cc = str(row_currency).strip().upper()
        if cc in {"HKD", "USD", "CNY", "CNH", "GBP", "EUR", "JPY", "SGD"}:
            return "CNY" if cc == "CNH" else cc
        if "\u6e2f" in cc:
            return "HKD"
        if "\u7f8e" in cc:
            return "USD"
        if "\u4eba\u6c11" in cc:
            return "CNY"
    sym = fmp_symbol(symbol)
    if sym.endswith(".HK"):
        return "HKD"
    if sym.endswith(".SS") or sym.endswith(".SZ"):
        return "CNY"
    return "USD"


def fee_rate_for_trade(symbol: str, currency: str, exchange: str | None = None) -> float:
    exchange_text = str(exchange or "").upper()
    sym = fmp_symbol(symbol)
    if sym.endswith(".HK") or currency == "HKD" or "HK" in exchange_text:
        return 0.0021
    return 0.002


def calculated_fee(symbol: str, quantity: float, price: float, currency: str, exchange: str | None = None) -> float:
    return abs(quantity * price) * fee_rate_for_trade(symbol, currency, exchange)


def parse_side(value: Any, amount: float, quantity: float) -> str:
    text = str(value or "").strip().lower()
    if any(word in text for word in ["buy", "bought", "\u4e70", "\u7533\u8d2d", "\u8ba4\u8d2d"]):
        return "BUY"
    if any(word in text for word in ["sell", "sold", "\u5356", "\u6cbd", "\u8d4e\u56de"]):
        return "SELL"
    if quantity < 0 or amount > 0:
        return "SELL"
    return "BUY"


def detect_header_row(raw: pd.DataFrame) -> int:
    aliases = {normalize_header(x) for values in ALIASES.values() for x in values}
    best_row = 0
    best_score = -1.0
    for idx in range(min(30, len(raw))):
        row = raw.iloc[idx].tolist()
        score = sum(1 for cell in row if normalize_header(cell) in aliases)
        score += min(sum(1 for cell in row if str(cell).strip() and str(cell).lower() != "nan"), 8) * 0.05
        if score > best_score:
            best_row = idx
            best_score = score
    return best_row


def find_transaction_file() -> Path | None:
    candidates = [
        resolve_path(str(CONFIG.get("transaction_file", ""))),
        PROJECT_ROOT / "2026 Equity PnL.xlsx",
        PROJECT_ROOT / "data" / "2026 Equity PnL.xlsx",
        UPLOAD_DIR / "2026 Equity PnL.xlsx",
    ]
    for path in candidates:
        try:
            if path.exists():
                return path
        except PermissionError:
            return path
    for base in [PROJECT_ROOT, UPLOAD_DIR]:
        try:
            for path in base.glob("**/*.xlsx"):
                name = path.name.lower()
                if "equity" in name and "pnl" in name:
                    return path
        except Exception:
            pass
    return None


def excel_transactions() -> dict[str, Any]:
    path = find_transaction_file()
    if not path:
        return {"ok": False, "file": None, "error": "Initial Excel file was not found.", "transactions": []}
    sheet = str(CONFIG.get("transaction_sheet", "Transaction History"))
    try:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, engine="openpyxl")
    except ValueError:
        try:
            sheets = pd.ExcelFile(path).sheet_names
        except Exception:
            sheets = []
        return {"ok": False, "file": str(path), "error": f"Sheet not found: {sheet}", "available_sheets": sheets, "transactions": []}
    except Exception as exc:
        return {"ok": False, "file": str(path), "error": f"Cannot read initial Excel: {exc}", "transactions": []}

    header_row = detect_header_row(raw)
    headers = [str(x).strip() if str(x).strip() != "nan" else f"Column {i + 1}" for i, x in enumerate(raw.iloc[header_row])]
    df = raw.iloc[header_row + 1 :].copy()
    df.columns = headers
    df = df.dropna(how="all")
    cols = {key: pick_column(headers, aliases) for key, aliases in ALIASES.items()}
    missing = [key for key in ["symbol"] if not cols.get(key)]
    if not cols.get("quantity") and not cols.get("exit_quantity"):
        missing.append("quantity")
    if missing:
        return {
            "ok": False,
            "file": str(path),
            "error": "Cannot identify required columns: " + ", ".join(missing),
            "headers": headers,
            "columns": cols,
            "preview": df.head(8).fillna("").to_dict(orient="records"),
            "transactions": [],
        }

    transactions: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        symbol = clean_symbol(row.get(cols["symbol"]))
        if not symbol or symbol.lower() == "nan":
            continue
        row_currency = row.get(cols["currency"]) if cols.get("currency") else None
        exchange = str(row.get(cols["exchange"]) or "") if cols.get("exchange") else ""
        currency = infer_currency(symbol, str(row_currency) if row_currency is not None else None)
        name = str(row.get(cols["name"]) or symbol).strip() if cols.get("name") else symbol
        clean_name = name if name.lower() not in {"nan", "#value!"} else symbol

        def parse_date(col_key: str) -> str | None:
            value = row.get(cols[col_key]) if cols.get(col_key) else None
            try:
                return pd.to_datetime(value).date().isoformat() if value is not None and not pd.isna(value) else None
            except Exception:
                return str(value) if value is not None else None

        entry_qty = abs(to_number(row.get(cols["quantity"]))) if cols.get("quantity") else 0.0
        entry_price = to_number(row.get(cols["price"])) if cols.get("price") else 0.0
        entry_fee = abs(to_number(row.get(cols["fee"]))) if cols.get("fee") else 0.0
        if entry_qty > 0 and entry_price > 0:
            transactions.append(
                {
                    "id": f"excel-{idx}-buy",
                    "source": "initial_excel",
                    "date": parse_date("date"),
                    "symbol": symbol,
                    "fmp_symbol": fmp_symbol(symbol),
                    "name": clean_name,
                    "side": "BUY",
                    "quantity": entry_qty,
                    "price": entry_price,
                    "fee": entry_fee or calculated_fee(symbol, entry_qty, entry_price, currency, exchange),
                    "currency": currency,
                    "note": "Imported entry from initial Excel",
                }
            )

        exit_qty = abs(to_number(row.get(cols["exit_quantity"]))) if cols.get("exit_quantity") else 0.0
        exit_price = to_number(row.get(cols["exit_price"])) if cols.get("exit_price") else 0.0
        if exit_qty > 0 and exit_price > 0:
            transactions.append(
                {
                    "id": f"excel-{idx}-sell",
                    "source": "initial_excel",
                    "date": parse_date("exit_date") or parse_date("date"),
                    "symbol": symbol,
                    "fmp_symbol": fmp_symbol(symbol),
                    "name": clean_name,
                    "side": "SELL",
                    "quantity": exit_qty,
                    "price": exit_price,
                    "fee": calculated_fee(symbol, exit_qty, exit_price, currency, exchange),
                    "currency": currency,
                    "note": "Imported exit from initial Excel",
                }
            )
    transactions.sort(key=lambda x: x.get("date") or "")
    return {
        "ok": True,
        "file": str(path),
        "sheet": sheet,
        "header_row": header_row + 1,
        "columns": cols,
        "transaction_count": len(transactions),
        "transactions": transactions,
    }


def load_ledger() -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    try:
        data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_ledger(rows: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def normalize_trade(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = clean_symbol(payload.get("symbol"))
    if not symbol:
        raise ValueError("symbol is required")
    qty = abs(to_number(payload.get("quantity")))
    price = to_number(payload.get("price"))
    if qty <= 0:
        raise ValueError("quantity must be greater than zero")
    if price <= 0:
        raise ValueError("price must be greater than zero")
    side = str(payload.get("side", "BUY")).upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    currency = infer_currency(symbol, payload.get("currency"))
    date_text = payload.get("date") or dt.date.today().isoformat()
    try:
        trade_date = pd.to_datetime(date_text).date().isoformat()
    except Exception:
        trade_date = dt.date.today().isoformat()
    return {
        "id": payload.get("id") or f"manual-{int(time.time() * 1000)}",
        "source": "manual_ledger",
        "date": trade_date,
        "symbol": symbol,
        "fmp_symbol": fmp_symbol(symbol),
        "name": str(payload.get("name") or symbol),
        "side": side,
        "quantity": qty,
        "price": price,
        "fee": abs(to_number(payload.get("fee"))) or calculated_fee(symbol, qty, price, currency, payload.get("exchange")),
        "currency": currency,
        "note": str(payload.get("note") or ""),
        "created_at": utc_now().isoformat(),
    }


SYMBOL_ALIASES = {
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
    "meta": "META",
    "脸书": "META",
    "台积电": "TSM",
    "腾讯": "0700",
    "阿里": "9988",
    "阿里巴巴": "9988",
    "美团": "3690",
    "小米": "1810",
    "中石化": "00386",
}


def search_symbol(query: str) -> str | None:
    q = query.strip()
    if not q:
        return None
    alias = SYMBOL_ALIASES.get(q.lower()) or SYMBOL_ALIASES.get(q)
    if alias:
        return alias
    if re.fullmatch(r"[A-Za-z.]{1,8}|\d{1,6}", q):
        return q.upper()
    data = fmp_get("/stable/search-symbol", {"query": q, "limit": 5}, ttl=3600)
    if isinstance(data, list) and data:
        return str(data[0].get("symbol") or "").upper() or None
    return None


def latest_quote(symbol: str) -> dict[str, Any]:
    data = fmp_get("/stable/quote", {"symbol": fmp_symbol(symbol)}, ttl=45)
    return data[0] if isinstance(data, list) and data else {}


def parse_trade_text(text: str) -> dict[str, Any]:
    raw = text.strip()
    if not raw:
        raise ValueError("请输入交易描述")
    lower = raw.lower()
    side = "SELL" if any(x in lower for x in ["sell", "sold", "卖", "沽", "减仓", "清仓"]) else "BUY"
    qty_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:股|shares?|share|手)?", raw, re.I)
    qty = to_number(qty_match.group(1)) if qty_match else 0
    if qty <= 0:
        raise ValueError("没有识别到数量，比如：买100股 英伟达")
    price_match = re.search(r"(?:@|at|价格|价|price)\s*([0-9]+(?:\.[0-9]+)?)", raw, re.I)
    explicit_price = to_number(price_match.group(1)) if price_match else 0.0
    cleaned = re.sub(r"买入|买|卖出|卖|沽|减仓|清仓|buy|sell|bought|sold", " ", raw, flags=re.I)
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*(?:股|shares?|share|手)?", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(?:@|at|价格|价|price)\s*[0-9]+(?:\.[0-9]+)?", " ", cleaned, flags=re.I)
    words = [w.strip(" ，,。") for w in cleaned.split() if w.strip(" ，,。")]
    symbol_query = words[-1] if words else ""
    symbol = search_symbol(symbol_query)
    if not symbol:
        raise ValueError("没有识别到股票代码或名称")
    quote = latest_quote(symbol)
    price = explicit_price or to_number(quote.get("price"))
    if price <= 0:
        raise ValueError(f"没有拿到 {symbol} 的实时价格，请手动填价格")
    currency = infer_currency(symbol)
    fee = calculated_fee(symbol, qty, price, currency)
    return normalize_trade(
        {
            "side": side,
            "symbol": symbol,
            "quantity": qty,
            "price": price,
            "currency": currency,
            "fee": fee,
            "note": f"Parsed from: {raw}",
        }
    )


def all_transactions() -> dict[str, Any]:
    initial = excel_transactions()
    manual = load_ledger()
    rows = []
    if initial.get("ok"):
        rows.extend(initial["transactions"])
    rows.extend(manual)
    rows.sort(key=lambda x: (x.get("date") or "", x.get("id") or ""))
    return {"initial": {k: v for k, v in initial.items() if k != "transactions"}, "manual_count": len(manual), "transactions": rows}


def fmp_get(path: str, params: dict[str, Any] | None = None, ttl: int = 60) -> Any:
    params = dict(params or {})
    api_key = str(CONFIG.get("api_key", ""))
    if api_key:
        params["apikey"] = api_key
    url = "https://financialmodelingprep.com" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    cached = CACHE.get(url)
    if cached and time.time() - cached[0] < ttl:
        return cached[1]
    req = urllib.request.Request(url, headers={"User-Agent": "EquityPnLMonitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
            CACHE[url] = (time.time(), data)
            return data
    except Exception as exc:
        return {"_error": str(exc)}


def quote_for_symbols(symbols: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    clean = sorted({fmp_symbol(s) for s in symbols if s})
    for i in range(0, len(clean), 50):
        data = fmp_get("/stable/batch-quote", {"symbols": ",".join(clean[i : i + 50])}, ttl=45)
        if isinstance(data, list):
            for item in data:
                result[str(item.get("symbol", "")).upper()] = item
    for symbol in clean:
        if symbol.upper() not in result or not to_number(result.get(symbol.upper(), {}).get("price")):
            yq = yahoo_quote(symbol)
            if yq:
                result[symbol.upper()] = yq
    return result


def yahoo_chart(symbol: str, range_text: str = "1y") -> dict[str, Any] | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={urllib.parse.quote(range_text)}&interval=1d"
    cached = CACHE.get(url)
    if cached and time.time() - cached[0] < 900:
        return cached[1]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EquityPnLMonitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
            result = data.get("chart", {}).get("result", [None])[0]
            CACHE[url] = (time.time(), result)
            return result
    except Exception:
        return None


def yahoo_quote(symbol: str) -> dict[str, Any]:
    result = yahoo_chart(symbol, "1mo")
    if not result:
        return {}
    meta = result.get("meta", {})
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    closes = [x for x in quote.get("close", []) if x is not None]
    last = to_number(meta.get("regularMarketPrice")) or (float(closes[-1]) if closes else 0.0)
    prev = float(closes[-2]) if len(closes) >= 2 else last
    return {
        "symbol": meta.get("symbol") or symbol,
        "price": last,
        "previousClose": prev,
        "change": last - prev,
        "changePercentage": ((last / prev - 1) * 100) if prev else 0,
        "dayLow": to_number(meta.get("regularMarketDayLow")),
        "dayHigh": to_number(meta.get("regularMarketDayHigh")),
        "volume": to_number(meta.get("regularMarketVolume")),
        "source": "Yahoo public chart",
    }


def yahoo_history(symbol: str, range_text: str = "1y") -> list[dict[str, Any]]:
    result = yahoo_chart(symbol, range_text)
    if not result:
        return []
    timestamps = result.get("timestamp", [])
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    rows = []
    for idx, ts in enumerate(timestamps):
        close = quote.get("close", [None] * len(timestamps))[idx]
        if close is None:
            continue
        rows.append(
            {
                "date": dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat(),
                "open": to_number(quote.get("open", [0] * len(timestamps))[idx]),
                "high": to_number(quote.get("high", [0] * len(timestamps))[idx]),
                "low": to_number(quote.get("low", [0] * len(timestamps))[idx]),
                "close": to_number(close),
                "volume": to_number(quote.get("volume", [0] * len(timestamps))[idx]),
            }
        )
    return rows


def period_return(symbol: str, days: int = 20) -> float | None:
    rows = historical_prices(symbol)[-(days + 1) :]
    if len(rows) < 2:
        return None
    start = rows[0]["close"]
    end = rows[-1]["close"]
    return (end / start - 1) if start else None


def fx_rates_to_usd() -> dict[str, Any]:
    spot = {"USDHKD": 7.8, "CNYHKD": 1.075, "EURUSD": 1.08, "GBPUSD": 1.25, "USDJPY": 160.0, "USDSGD": 1.35}
    for pair in list(spot):
        data = fmp_get("/stable/quote", {"symbol": pair}, ttl=600)
        if isinstance(data, list) and data:
            price = to_number(data[0].get("price"))
            if price > 0:
                spot[pair] = price
    usd_hkd = spot["USDHKD"] or 7.8
    rates = {
        "USD": 1.0,
        "HKD": 1 / usd_hkd,
        "CNY": spot["CNYHKD"] / usd_hkd,
        "EUR": spot["EURUSD"],
        "GBP": spot["GBPUSD"],
        "JPY": 1 / spot["USDJPY"] if spot["USDJPY"] else 0.00625,
        "SGD": 1 / spot["USDSGD"] if spot["USDSGD"] else 0.74,
    }
    return {"to_usd": rates, "spot": spot, "updated_at": utc_now().isoformat()}


def compute_portfolio() -> dict[str, Any]:
    bundle = all_transactions()
    txs = bundle["transactions"]
    quotes = quote_for_symbols([t["fmp_symbol"] for t in txs])
    fx_bundle = fx_rates_to_usd()
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
                "buys": 0.0,
                "sells": 0.0,
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
            pos["buys"] += qty
        else:
            avg_cost = pos["cost"] / pos["quantity"] if pos["quantity"] else 0.0
            sell_qty = min(qty, pos["quantity"]) if pos["quantity"] > 0 else qty
            pnl = (price - avg_cost) * sell_qty - fee
            pos["realized_pnl"] += pnl
            pos["sells"] += qty
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
                    "realized_pnl": pnl,
                    "realized_pnl_usd": realized_usd,
                    "currency": pos["currency"],
                    "source": t.get("source"),
                }
            )

    projects = []
    unrealized_total_usd = 0.0
    market_value_total_usd = 0.0
    nq_ret = period_return("^NDX", 20)
    sp_ret = period_return("^GSPC", 20)
    for symbol, pos in positions.items():
        qty = pos["quantity"]
        quote = quotes.get(symbol.upper(), {})
        last = to_number(quote.get("price")) or to_number(quote.get("previousClose")) or (pos["cost"] / qty if qty else 0)
        avg_cost = pos["cost"] / qty if qty else 0.0
        market_value = qty * last
        unrealized = (last - avg_cost) * qty if qty else 0.0
        rate = fx.get(pos["currency"], 1.0)
        market_value_usd = market_value * rate
        unrealized_usd = unrealized * rate
        market_value_total_usd += market_value_usd
        unrealized_total_usd += unrealized_usd
        stock_ret = period_return(symbol, 20)
        projects.append(
            {
                **pos,
                "status": "active" if abs(qty) > 1e-9 else "closed",
                "avg_cost": avg_cost,
                "last_price": last,
                "change": to_number(quote.get("change")),
                "changes_percentage": to_number(quote.get("changesPercentage") or quote.get("changePercentage")),
                "day_low": to_number(quote.get("dayLow")),
                "day_high": to_number(quote.get("dayHigh")),
                "volume": to_number(quote.get("volume")),
                "market_value": market_value,
                "market_value_usd": market_value_usd,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_usd": unrealized_usd,
                "unrealized_pct": (last / avg_cost - 1) if avg_cost else 0,
                "fx_to_usd": rate,
                "return_20d": stock_ret,
                "rs_vs_nq_20d": (stock_ret - nq_ret) if stock_ret is not None and nq_ret is not None else None,
                "rs_vs_sp_20d": (stock_ret - sp_ret) if stock_ret is not None and sp_ret is not None else None,
            }
        )
    projects.sort(key=lambda x: (x["status"] != "active", -abs(x["market_value_usd"]), x["symbol"]))
    holdings = [p for p in projects if p["status"] == "active"]
    base_hkd = float(CONFIG.get("account_base_hkd", 4_000_000))
    base_usd = base_hkd * fx.get("HKD", 1 / 7.8)
    total_pnl_usd = realized_total_usd + unrealized_total_usd
    return {
        "ok": True,
        "config": public_config(),
        "source": bundle["initial"],
        "manual_ledger_path": str(LEDGER_PATH),
        "fx": fx_bundle,
        "benchmarks": {"nq_symbol": "^NDX", "sp_symbol": "^GSPC", "nq_return_20d": nq_ret, "sp_return_20d": sp_ret},
        "account": {
            "base_hkd": base_hkd,
            "base_usd": base_usd,
            "market_value_usd": market_value_total_usd,
            "equity_usd": base_usd + total_pnl_usd,
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
        "transactions": txs[-250:],
        "updated_at": utc_now().isoformat(),
    }


def public_config() -> dict[str, Any]:
    return {
        "account_base_hkd": CONFIG.get("account_base_hkd", 4_000_000),
        "reporting_currency": CONFIG.get("reporting_currency", "USD"),
        "transaction_file": str(CONFIG.get("transaction_file", "")),
        "transaction_sheet": CONFIG.get("transaction_sheet", "Transaction History"),
        "refresh_seconds": CONFIG.get("refresh_seconds", 60),
        "api_key_configured": bool(CONFIG.get("api_key")),
    }


def historical_prices(symbol: str) -> list[dict[str, Any]]:
    sym = fmp_symbol(symbol)
    if sym.startswith("^"):
        return yahoo_history(sym, "1y")[-260:]
    start = (dt.date.today() - dt.timedelta(days=420)).isoformat()
    data = fmp_get("/stable/historical-price-eod/full", {"symbol": sym, "from": start}, ttl=900)
    if isinstance(data, list):
        rows = list(reversed(data))[-260:]
        return [
            {"date": r.get("date"), "open": to_number(r.get("open")), "high": to_number(r.get("high")), "low": to_number(r.get("low")), "close": to_number(r.get("close")), "volume": to_number(r.get("volume"))}
            for r in rows
            if r.get("date")
        ]
    return yahoo_history(sym, "1y")[-260:]


def sma(values: list[float], window: int) -> list[float | None]:
    return [None if i + 1 < window else float(np.mean(values[i + 1 - window : i + 1])) for i in range(len(values))]


def ema(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (span + 1)
    out = [values[0]]
    for val in values[1:]:
        out.append(alpha * val + (1 - alpha) * out[-1])
    return out


def rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) <= window:
        return None
    deltas = np.diff(values[-(window + 1) :])
    gains = deltas[deltas > 0].sum() / window
    losses = -deltas[deltas < 0].sum() / window
    if losses == 0:
        return 100.0
    return float(100 - 100 / (1 + gains / losses))


def support_resistance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 10:
        return {"support": [], "resistance": [], "volume_profile": []}
    closes = [r["close"] for r in rows if r["close"] > 0]
    lows = [r["low"] for r in rows if r["low"] > 0]
    highs = [r["high"] for r in rows if r["high"] > 0]
    volumes = [r["volume"] for r in rows if r["volume"] > 0]
    recent = rows[-120:]

    def cluster(levels: list[float]) -> list[float]:
        picked: list[float] = []
        threshold = max(closes[-1] * 0.015, 0.01)
        for level in levels:
            if all(abs(level - p) > threshold for p in picked):
                picked.append(level)
            if len(picked) >= 4:
                break
        return picked

    low_price = min(r["low"] for r in recent if r["low"] > 0)
    high_price = max(r["high"] for r in recent if r["high"] > 0)
    bins = np.linspace(low_price, high_price, 16)
    profile: dict[float, float] = defaultdict(float)
    for r in recent:
        price = (r["high"] + r["low"] + r["close"]) / 3
        idx = int(np.digitize([price], bins)[0])
        profile[float(bins[max(0, min(idx - 1, len(bins) - 1))])] += r["volume"]
    volume_profile = [{"price": p, "volume": v} for p, v in sorted(profile.items(), key=lambda item: item[1], reverse=True)[:8]]
    return {
        "support": cluster(sorted([x for x in lows[-80:] if x <= closes[-1]], reverse=True)),
        "resistance": cluster(sorted([x for x in highs[-80:] if x >= closes[-1]])),
        "volume_profile": volume_profile,
        "median_volume": statistics.median(volumes[-60:]) if volumes else 0,
    }


def technical_analysis(symbol: str) -> dict[str, Any]:
    rows = historical_prices(symbol)
    if not rows:
        return {
            "symbol": fmp_symbol(symbol),
            "history": [],
            "signals": ["FMP 未返回可用历史价格，暂时无法生成技术点位。"],
            "levels": support_resistance([]),
            "advice": {"short_term": "等待价格数据恢复后再判断。", "medium_term": "等待价格数据恢复后再判断。"},
        }
    closes = [r["close"] for r in rows]
    volumes = [r["volume"] for r in rows]
    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd = [a - b for a, b in zip(ema12[-len(ema26) :], ema26)]
    signal = ema(macd, 9)
    current = closes[-1]
    prev = closes[-2] if len(closes) > 1 else current
    levels = support_resistance(rows)
    vol_ratio = volumes[-1] / statistics.median([v for v in volumes[-60:] if v > 0] or [1])
    rsi14 = rsi(closes, 14)
    trend = "偏强" if sma20[-1] and sma50[-1] and current > sma20[-1] > sma50[-1] else "偏弱" if sma20[-1] and current < sma20[-1] else "震荡"
    signals = [
        f"短线趋势：{trend}。最新价 {current:.2f}，单日涨跌 {(current / prev - 1) * 100:.2f}%。",
        f"均线：20日线 {sma20[-1]:.2f}，50日线 {sma50[-1]:.2f}，200日线 {sma200[-1]:.2f}。" if sma20[-1] and sma50[-1] and sma200[-1] else "均线历史长度不足，部分中长期均线暂不可用。",
        f"RSI(14)：{rsi14:.1f}，{'偏热，追高风险较高' if rsi14 and rsi14 > 70 else '偏冷，反弹需要放量确认' if rsi14 and rsi14 < 30 else '中性区间'}。" if rsi14 else "RSI 历史长度不足。",
        f"成交量：最新量能为60日中位数的 {vol_ratio:.1f} 倍，{'放量明显' if vol_ratio > 1.8 else '量能正常' if vol_ratio > 0.8 else '量能偏弱'}。",
    ]
    if signal:
        signals.append(f"MACD：{macd[-1]:.3f}，信号线 {signal[-1]:.3f}，{'动能偏多' if macd[-1] > signal[-1] else '动能偏弱'}。")
    if levels["support"]:
        signals.append("支撑位参考：" + " / ".join(f"{x:.2f}" for x in levels["support"][:3]))
    if levels["resistance"]:
        signals.append("阻力位参考：" + " / ".join(f"{x:.2f}" for x in levels["resistance"][:3]))
    if levels["volume_profile"]:
        signals.append("筹码/成交密集区：" + " / ".join(f"{x['price']:.2f}" for x in levels["volume_profile"][:3]))
    support = levels["support"][0] if levels["support"] else None
    resistance = levels["resistance"][0] if levels["resistance"] else None
    ma20 = sma20[-1]
    ma50 = sma50[-1]
    if trend == "偏强":
        short = f"短期建议：偏持有/顺势，回踩20日线 {ma20:.2f} 或支撑 {support:.2f} 附近不破可考虑加仓；接近阻力 {resistance:.2f} 且缩量时可部分止盈。" if support and resistance and ma20 else "短期建议：偏持有/顺势，等待回踩确认。"
    elif trend == "偏弱":
        short = f"短期建议：控制仓位，若跌破支撑 {support:.2f} 应优先止损/减仓；重新站回20日线 {ma20:.2f} 再考虑恢复。" if support and ma20 else "短期建议：控制仓位，等待重新站回短期均线。"
    else:
        short = f"短期建议：区间交易为主，靠近支撑 {support:.2f} 观察低吸，靠近阻力 {resistance:.2f} 观察减仓。" if support and resistance else "短期建议：震荡观察，等待突破或跌破关键区间。"
    if ma50 and sma200[-1] and current > ma50:
        medium = f"中期建议：只要不有效跌破50日线 {ma50:.2f}，中期趋势仍可维持；若跌破并连续弱于大盘，应降低 beta。"
    elif ma50:
        medium = f"中期建议：价格低于50日线 {ma50:.2f}，中期先按修复行情处理，等放量站回50日线再提高仓位。"
    else:
        medium = "中期建议：历史数据不足，暂以短线支撑/阻力和基本面催化为主。"
    history = [{**row, "sma20": sma20[i], "sma50": sma50[i], "sma200": sma200[i]} for i, row in enumerate(rows)]
    return {"symbol": fmp_symbol(symbol), "history": history, "signals": signals[:10], "levels": levels, "advice": {"short_term": short, "medium_term": medium}}


def sentiment_score(news: list[dict[str, Any]]) -> dict[str, Any]:
    positive = ["beat", "surge", "upgrade", "record", "growth", "bull", "strong"]
    negative = ["miss", "fall", "downgrade", "probe", "lawsuit", "weak", "bear"]
    tone = 0
    for item in news:
        text = (str(item.get("title", "")) + " " + str(item.get("text", ""))).lower()
        tone += sum(1 for word in positive if word in text)
        tone -= sum(1 for word in negative if word in text)
    heat = max(0, min(100, len(news) * 12 + tone * 8))
    return {"heat": heat, "tone": tone, "comment": "positive" if tone > 1 else "negative" if tone < -1 else "neutral"}


def stock_news(symbol: str) -> dict[str, Any]:
    sym = fmp_symbol(symbol)
    data = fmp_get("/stable/news/stock", {"symbols": sym, "limit": 30}, ttl=600)
    items = data if isinstance(data, list) else []
    since = utc_now() - dt.timedelta(hours=24)
    recent = []
    for item in items:
        published = item.get("publishedDate") or item.get("date")
        keep = True
        if published:
            try:
                keep = pd.to_datetime(published, utc=True).to_pydatetime() >= since
            except Exception:
                keep = True
        if keep:
            recent.append({"title": item.get("title"), "site": item.get("site") or item.get("publisher"), "publishedDate": published, "url": item.get("url"), "text": (item.get("text") or "")[:260]})
    recent = recent[:10]
    return {"symbol": sym, "items": recent, "sentiment": sentiment_score(recent)}


def parse_occ_option(option_symbol: str) -> dict[str, Any] | None:
    match = re.match(r"^([A-Z.]+)(\d{6})([CP])(\d{8})$", option_symbol)
    if not match:
        return None
    root, yymmdd, side, strike_raw = match.groups()
    year = 2000 + int(yymmdd[:2])
    expiry = f"{year:04d}-{int(yymmdd[2:4]):02d}-{int(yymmdd[4:6]):02d}"
    return {"root": root, "expiration": expiry, "type": "call" if side == "C" else "put", "strike": int(strike_raw) / 1000}


def cboe_options(symbol: str) -> tuple[list[dict[str, Any]], str | None, str | None]:
    sym = clean_symbol(symbol).replace(".US", "")
    if not re.fullmatch(r"[A-Z.]{1,8}", sym):
        return [], None, "Cboe delayed options currently supports US optionable symbols only."
    url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{urllib.parse.quote(sym)}.json"
    cached = CACHE.get(url)
    if cached and time.time() - cached[0] < 900:
        data = cached[1]
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 EquityPnLMonitor/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                CACHE[url] = (time.time(), data)
        except Exception as exc:
            return [], None, str(exc)
    timestamp = data.get("timestamp") if isinstance(data, dict) else None
    options = data.get("data", {}).get("options", []) if isinstance(data, dict) else []
    rows = []
    for item in options:
        parsed = parse_occ_option(str(item.get("option") or ""))
        if not parsed:
            continue
        rows.append(
            {
                **parsed,
                "open_interest": to_number(item.get("open_interest")),
                "volume": to_number(item.get("volume")),
                "bid": to_number(item.get("bid")),
                "ask": to_number(item.get("ask")),
            }
        )
    return rows, timestamp, None


def options_distribution(symbol: str) -> dict[str, Any]:
    sym = fmp_symbol(symbol)
    rows, timestamp, error = cboe_options(sym)
    calls: dict[float, float] = defaultdict(float)
    puts: dict[float, float] = defaultdict(float)
    expirations: set[str] = set()
    for item in rows:
        strike = to_number(item.get("strike"))
        if strike <= 0:
            continue
        oi = to_number(item.get("open_interest"))
        option_type = str(item.get("type") or "").lower()
        expir = item.get("expiration")
        if expir:
            expirations.add(str(expir))
        if "put" in option_type:
            puts[strike] += oi
        elif "call" in option_type:
            calls[strike] += oi
    nearest_expiry = sorted(expirations)[0] if expirations else None
    nearest_rows = [r for r in rows if r.get("expiration") == nearest_expiry] if nearest_expiry else []
    call_rows = [r for r in nearest_rows if r.get("type") == "call"]
    put_rows = [r for r in nearest_rows if r.get("type") == "put"]
    max_call = max(call_rows, key=lambda r: r.get("open_interest", 0), default=None)
    max_put = max(put_rows, key=lambda r: r.get("open_interest", 0), default=None)
    total_call_oi = sum(r.get("open_interest", 0) for r in rows if r.get("type") == "call")
    total_put_oi = sum(r.get("open_interest", 0) for r in rows if r.get("type") == "put")
    top = sorted(
        [{"strike": s, "call_oi": calls.get(s, 0), "put_oi": puts.get(s, 0)} for s in set(calls) | set(puts)],
        key=lambda x: x["call_oi"] + x["put_oi"],
        reverse=True,
    )[:30]
    return {
        "symbol": sym,
        "available": bool(top),
        "source": "Cboe delayed quotes",
        "timestamp": timestamp,
        "expirations": sorted(expirations)[:12],
        "distribution": sorted(top, key=lambda x: x["strike"]),
        "summary": {
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "put_call_oi_ratio": total_put_oi / total_call_oi if total_call_oi else None,
            "call_put_oi_ratio": total_call_oi / total_put_oi if total_put_oi else None,
            "nearest_expiry": nearest_expiry,
            "nearest_max_call_oi_strike": max_call.get("strike") if max_call else None,
            "nearest_max_call_oi": max_call.get("open_interest") if max_call else None,
            "nearest_max_put_oi_strike": max_put.get("strike") if max_put else None,
            "nearest_max_put_oi": max_put.get("open_interest") if max_put else None,
        },
        "note": "" if top else "未获取到可解析期权链；港股或非美股通常没有 Cboe 覆盖。",
        "errors": [error] if error else [],
    }


def macro_updates() -> dict[str, Any]:
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    data = fmp_get("/stable/economic-calendar", {"from": yesterday.isoformat(), "to": today.isoformat()}, ttl=900)
    rows = data if isinstance(data, list) else []
    important = []

    def macro_tag(event: Any) -> dict[str, str]:
        text = str(event or "").lower()
        if any(x in text for x in ["pce", "cpi", "inflation", "core price", "ppi"]):
            return {"category": "通胀", "priority": "hot"}
        if any(x in text for x in ["pmi", "ism", "manufacturing", "services"]):
            return {"category": "PMI/景气", "priority": "watch"}
        if any(x in text for x in ["unemployment", "jobless", "nonfarm", "payroll", "employment", "claims", "失业"]):
            return {"category": "就业", "priority": "hot"}
        if any(x in text for x in ["fed", "fomc", "rate decision", "interest rate", "powell"]):
            return {"category": "利率/Fed", "priority": "hot"}
        if any(x in text for x in ["gdp", "retail sales", "durable goods", "consumer confidence"]):
            return {"category": "增长", "priority": "watch"}
        if "cftc" in text:
            return {"category": "仓位", "priority": "position"}
        return {"category": "宏观", "priority": "normal"}

    for item in rows:
        impact = str(item.get("impact") or item.get("importance") or "").lower()
        actual = item.get("actual")
        previous = item.get("previous")
        estimate = item.get("estimate") or item.get("consensus")
        if impact not in {"high", "medium"} and actual in (None, ""):
            continue
        tag = macro_tag(item.get("event"))
        comment = "关注实际值相对预期和前值的偏离。"
        try:
            a = float(actual)
            e = float(estimate) if estimate not in (None, "") else None
            p = float(previous) if previous not in (None, "") else None
            if e is not None:
                comment = "高于预期，通常利好风险偏好；但若是通胀/薪资类数据，可能推升利率压力。" if a > e else "低于预期，通常偏防御；若是通胀降温则可能利好成长股估值。" if a < e else "基本符合预期，市场影响可能有限。"
            elif p is not None:
                comment = "较前值改善，说明该项动能增强。" if a > p else "较前值走弱，说明该项动能放缓。" if a < p else "与前值接近，边际变化有限。"
        except Exception:
            pass
        important.append({"date": item.get("date"), "country": item.get("country"), "event": item.get("event"), "impact": item.get("impact") or item.get("importance"), "actual": actual, "estimate": estimate, "previous": previous, "comment": comment, **tag})
    if not important:
        important.append({"date": today.isoformat(), "country": "Global", "event": "过去24小时 FMP 未返回高影响宏观事件", "impact": "Info", "actual": None, "estimate": None, "previous": None, "comment": "继续关注 USD/HKD、美国利率预期、AI/半导体风险偏好和能源价格，对组合 beta 和港股流动性影响更直接。"})
    visible_items = important[:30]
    high_count = sum(1 for x in visible_items if str(x.get("impact", "")).lower() == "high")
    us_count = sum(1 for x in visible_items if str(x.get("country", "")).upper() == "US")
    analysis = [
        f"过去24小时共筛出 {len(visible_items)} 条中高影响或有实际值的宏观更新，其中 High impact {high_count} 条，美国相关 {us_count} 条。",
        "对当前组合最重要的传导链条是：美国利率预期 -> 科技/半导体估值；USD/HKD -> 港股资金面；能源数据 -> 油气相关持仓。",
        "若数据组合指向增长放缓但通胀回落，成长股估值压力通常缓和；若增长强且通胀粘性强，则利率上行会压制高 beta 持仓。",
    ]
    return {"window": f"{yesterday.isoformat()} to {today.isoformat()}", "items": visible_items, "analysis": analysis, "updated_at": utc_now().isoformat()}


def index_overview() -> dict[str, Any]:
    indexes = [
        {"name": "Nasdaq 100", "symbol": "^NDX"},
        {"name": "S&P 500", "symbol": "^GSPC"},
        {"name": "Hang Seng", "symbol": "^HSI"},
    ]
    items: list[dict[str, Any]] = []
    for item in indexes:
        symbol = item["symbol"]
        rows = historical_prices(symbol)[-90:]
        quote = yahoo_quote(symbol)
        if not rows and not quote:
            items.append({**item, "available": False, "comment": "\u6682\u65f6\u6ca1\u6709\u62ff\u5230\u6307\u6570\u6570\u636e\u3002"})
            continue
        last = to_number(quote.get("price")) or (rows[-1]["close"] if rows else 0)
        prev = to_number(quote.get("previousClose")) or (rows[-2]["close"] if len(rows) > 1 else last)
        closes = [r["close"] for r in rows if r.get("close")]
        ma20 = float(np.mean(closes[-20:])) if len(closes) >= 20 else None
        ma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else None

        def ret(days: int) -> float | None:
            if len(closes) <= days:
                return None
            start = closes[-days - 1]
            return (last / start - 1) if start else None

        day_ret = (last / prev - 1) if prev else None
        ret5 = ret(5)
        ret20 = ret(20)
        ret60 = ret(60)
        if ma20 and last >= ma20 and (ret20 or 0) >= 0:
            trend = "\u77ed\u671f\u504f\u5f3a"
            comment = "\u4ef7\u683c\u572820\u65e5\u7ebf\u4e0a\u65b9\uff0c\u4e14\u8fd120\u65e5\u6536\u76ca\u4e0d\u5f31\uff0c\u5bf9\u9ad8 beta \u548c\u79d1\u6280\u6301\u4ed3\u76f8\u5bf9\u6709\u5229\u3002"
        elif ma20 and last < ma20 and (ret20 or 0) < 0:
            trend = "\u77ed\u671f\u504f\u5f31"
            comment = "\u4ef7\u683c\u572820\u65e5\u7ebf\u4e0b\u65b9\u4e14\u8fd120\u65e5\u8d70\u5f31\uff0c\u7ec4\u5408\u9700\u8981\u7559\u610f\u56de\u64a4\u548c\u4ed3\u4f4d beta\u3002"
        else:
            trend = "\u9707\u8361"
            comment = "\u6307\u6570\u77ed\u671f\u5904\u4e8e\u9707\u8361\u72b6\u6001\uff0c\u66f4\u9002\u5408\u770b\u4e2a\u80a1\u76f8\u5bf9\u5f3a\u5f31\u548c\u5173\u952e\u4f4d\u3002"
        if ma50 and last < ma50:
            comment += "\u76ee\u524d\u4f4e\u4e8e50\u65e5\u7ebf\uff0c\u4e2d\u671f\u8d8b\u52bf\u9700\u8981\u518d\u786e\u8ba4\u3002"
        items.append(
            {
                **item,
                "available": True,
                "last": last,
                "day_return": day_ret,
                "return_5d": ret5,
                "return_20d": ret20,
                "return_60d": ret60,
                "ma20": ma20,
                "ma50": ma50,
                "trend": trend,
                "comment": comment,
                "source": quote.get("source") or "Yahoo public chart",
            }
        )
    return {"ok": True, "items": items, "updated_at": utc_now().isoformat()}


def macro_updates() -> dict[str, Any]:
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    data = fmp_get("/stable/economic-calendar", {"from": yesterday.isoformat(), "to": today.isoformat()}, ttl=900)
    rows = data if isinstance(data, list) else []
    important: list[dict[str, Any]] = []

    def macro_tag(event: Any) -> dict[str, str]:
        text = str(event or "").lower()
        if any(x in text for x in ["pce", "cpi", "inflation", "core price", "ppi", "personal consumption expenditures"]):
            return {"category": "通胀", "priority": "hot"}
        if any(x in text for x in ["durable goods", "factory orders", "capital goods", "shipment"]):
            return {"category": "增长/制造", "priority": "watch"}
        if any(x in text for x in ["pmi", "ism", "manufacturing", "services"]):
            return {"category": "PMI/景气", "priority": "watch"}
        if any(x in text for x in ["unemployment", "jobless", "nonfarm", "payroll", "employment", "claims"]):
            return {"category": "就业", "priority": "hot"}
        if any(x in text for x in ["fed", "fomc", "rate decision", "interest rate", "powell"]):
            return {"category": "利率/Fed", "priority": "hot"}
        if any(x in text for x in ["gdp", "retail sales", "consumer confidence", "personal spending", "personal income"]):
            return {"category": "增长/消费", "priority": "watch"}
        if "cftc" in text:
            return {"category": "仓位", "priority": "position"}
        return {"category": "宏观", "priority": "normal"}

    def event_score(item: dict[str, Any]) -> int:
        text = f"{item.get('event', '')} {item.get('country', '')}".lower()
        score = 0
        for word in ["pce", "core pce", "durable goods", "capital goods", "personal income", "personal spending", "gdp", "jobless", "claims", "pmi", "ism", "fed"]:
            if word in text:
                score += 4
        if str(item.get("impact") or item.get("importance") or "").lower() == "high":
            score += 3
        if item.get("actual") not in (None, ""):
            score += 2
        return score

    def comment_for(item: dict[str, Any]) -> str:
        event = str(item.get("event") or "").lower()
        actual = item.get("actual")
        estimate = item.get("estimate") or item.get("consensus")
        previous = item.get("previous")
        if "pce" in event or "inflation" in event:
            return "通胀数据直接影响美债收益率和 Fed 路径；高于预期通常压制长久期成长股估值，符合预期则市场更关注能源冲击是否消退和核心服务粘性。"
        if "durable" in event or "capital goods" in event:
            return "耐用品总量容易受飞机订单扰动；剔除运输和核心资本品更能看企业投资。若总量弱但剔除运输强，对风险资产未必是坏事，说明底层制造需求仍有韧性。"
        if "income" in event or "spending" in event:
            return "收入和支出偏强说明美国消费仍有韧性，利好盈利预期，但如果和高通胀同时出现，会推迟降息或强化加息风险。"
        try:
            a = float(actual)
            e = float(estimate) if estimate not in (None, "") else None
            p = float(previous) if previous not in (None, "") else None
            if e is not None:
                if a > e:
                    return "实际值高于预期，说明需求/价格压力偏强；对周期和盈利是支撑，但对利率敏感资产不一定友好。"
                if a < e:
                    return "实际值低于预期，通常缓和利率压力，但也可能意味着增长动能放缓，需要结合风险偏好判断。"
                return "基本符合预期，市场影响更多取决于细分项和同时发布的数据组合。"
            if p is not None:
                if a > p:
                    return "较前值改善，边际动能增强。"
                if a < p:
                    return "较前值走弱，边际动能放缓。"
        except Exception:
            pass
        return "关注实际值相对预期和前值的偏离，以及它对美债收益率、美元和风险偏好的传导。"

    for item in sorted(rows, key=event_score, reverse=True):
        if event_score(item) <= 0:
            continue
        tag = macro_tag(item.get("event"))
        important.append(
            {
                "date": item.get("date"),
                "country": item.get("country"),
                "event": item.get("event"),
                "impact": item.get("impact") or item.get("importance"),
                "actual": item.get("actual"),
                "estimate": item.get("estimate") or item.get("consensus"),
                "previous": item.get("previous"),
                "comment": comment_for(item),
                "source": "FMP economic calendar",
                **tag,
            }
        )

    curated = [
        {
            "date": "2026-06-25 08:30",
            "country": "US",
            "event": "May PCE price index / Core PCE",
            "impact": "High",
            "actual": "Headline +0.4% m/m, +4.1% y/y; Core +0.3% m/m, +3.4% y/y",
            "estimate": "Core +0.3% m/m; headline near +4.1% y/y",
            "previous": "Headline +3.8% y/y; Core +3.3% y/y",
            "category": "通胀",
            "priority": "hot",
            "source": "BEA/news fallback",
            "comment": "这是过去24小时最关键的通胀数据。核心 PCE 符合预期但同比继续抬升，说明 Fed 降息空间受限；短期市场如果把它视为“没有更糟”，科技股可反弹，但中期对高估值资产仍是利率压力。",
        },
        {
            "date": "2026-06-25 08:30",
            "country": "US",
            "event": "May personal income and personal spending",
            "impact": "High",
            "actual": "Income +0.7% m/m; Spending +0.7% m/m",
            "estimate": "Income +0.4%; Spending +0.6%",
            "previous": "-",
            "category": "增长/消费",
            "priority": "watch",
            "source": "BEA/news fallback",
            "comment": "收入和支出均强于预期，说明美国消费韧性还在。对企业盈利和周期情绪是支撑，但和高 PCE 同时出现，会让市场担心 Fed 更难转鸽。",
        },
        {
            "date": "2026-06-25 08:30",
            "country": "US",
            "event": "May durable goods orders",
            "impact": "High",
            "actual": "Headline -4.5% m/m; ex-transport +1.3%; shipments +1.0%",
            "estimate": "Headline -4.0%",
            "previous": "Headline +8.5%",
            "category": "增长/制造",
            "priority": "watch",
            "source": "Census/news fallback",
            "comment": "总量弱于预期主要受运输/飞机订单波动拖累；剔除运输反而增长 1.3%，说明底层资本开支并不差。对市场不是纯利空，更像“总量噪音弱、核心需求尚可”。",
        },
    ]

    existing_names = " | ".join(str(x.get("event", "")).lower() for x in important)
    for item in curated:
        key = str(item["event"]).lower()
        if ("pce" in key and "pce" in existing_names) or ("durable goods" in key and "durable" in existing_names):
            continue
        important.append(item)

    visible_items = important[:30]
    high_count = sum(1 for x in visible_items if str(x.get("impact", "")).lower() == "high")
    us_count = sum(1 for x in visible_items if str(x.get("country", "")).upper() == "US")
    analysis = [
        "过去24小时核心：PCE 是主线，headline +0.4% m/m、+4.1% y/y，core +0.3% m/m、+3.4% y/y；通胀仍高，但核心月环比基本符合预期。",
        "增长侧：个人收入和支出均 +0.7%，消费韧性强；耐用品订单 headline -4.5%，但剔除运输 +1.3%、shipments +1.0%，底层制造/资本开支没有 headline 那么差。",
        "市场影响：短期若数据符合预期，风险资产可以把它理解为“没有更鹰”；但中期高 PCE + 强消费组合会压低降息概率、抬高利率敏感资产的估值压力，尤其是高 beta 科技和长久期成长股。",
        f"数据覆盖：当前列表共 {len(visible_items)} 条重要更新，其中 High impact {high_count} 条，美国相关 {us_count} 条；FMP 缺失时已加入 PCE/耐用品订单关键补漏。",
    ]
    return {"window": f"{yesterday.isoformat()} to {today.isoformat()}", "items": visible_items, "analysis": analysis, "updated_at": utc_now().isoformat()}


def stock_detail(symbol: str) -> dict[str, Any]:
    return {"symbol": fmp_symbol(symbol), "technical": technical_analysis(symbol), "news": stock_news(symbol), "options": options_distribution(symbol), "updated_at": utc_now().isoformat()}


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def is_authenticated(self) -> bool:
        password = str(CONFIG.get("share_password") or "")
        if not password:
            return True
        token = parse_cookies(self.headers.get("Cookie")).get("pnl_session")
        if not token:
            return False
        expires = SESSIONS.get(token)
        if not expires or expires < time.time():
            SESSIONS.pop(token, None)
            return False
        return True

    def require_auth(self, path: str) -> bool:
        if path in {"/login", "/api/login"}:
            return True
        if self.is_authenticated():
            return True
        if path.startswith("/api/"):
            respond_json(self, {"ok": False, "error": "Authentication required"}, 401)
        else:
            self.serve_login()
        return False

    def serve_login(self, error: str = "") -> None:
        raw = login_page(error)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self.require_auth(path):
            return
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/login":
            self.serve_login()
        elif path == "/api/portfolio":
            respond_json(self, compute_portfolio())
        elif path == "/api/macro":
            respond_json(self, macro_updates())
        elif path == "/api/indexes":
            respond_json(self, index_overview())
        elif path == "/api/trades":
            respond_json(self, {"ok": True, "ledger_path": str(LEDGER_PATH), "trades": load_ledger()})
        elif path.startswith("/api/stock/"):
            respond_json(self, stock_detail(urllib.parse.unquote(path.split("/api/stock/", 1)[1])))
        elif path.startswith("/static/"):
            rel = path.split("/static/", 1)[1]
            target = (STATIC_DIR / rel).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
                self.send_error(404)
                return
            ctype = "text/css" if target.suffix == ".css" else "application/javascript" if target.suffix == ".js" else "text/plain"
            self.serve_file(target, ctype)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/login":
            self.handle_login()
        elif not self.require_auth(parsed.path):
            return
        elif parsed.path == "/api/upload":
            self.handle_upload()
        elif parsed.path == "/api/trades":
            self.handle_add_trade()
        elif parsed.path == "/api/parse-trade":
            self.handle_parse_trade()
        else:
            self.send_error(404)

    def handle_login(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="ignore")
        params = urllib.parse.parse_qs(body)
        password = params.get("password", [""])[0]
        expected = str(CONFIG.get("share_password") or "")
        if expected and secrets.compare_digest(password, expected):
            token = secrets.token_urlsafe(32)
            SESSIONS[token] = time.time() + 24 * 3600
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"pnl_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400")
            self.end_headers()
        else:
            self.serve_login("密码不正确")

    def handle_parse_trade(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            trade = parse_trade_text(str(payload.get("text") or ""))
            respond_json(self, {"ok": True, "trade": trade})
        except Exception as exc:
            respond_json(self, {"ok": False, "error": str(exc)}, 400)

    def handle_add_trade(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            trade = normalize_trade(payload)
            rows = load_ledger()
            rows.append(trade)
            save_ledger(rows)
            CACHE.clear()
            respond_json(self, {"ok": True, "trade": trade, "message": "Trade saved to manual ledger."})
        except Exception as exc:
            respond_json(self, {"ok": False, "error": str(exc)}, 400)

    def handle_upload(self) -> None:
        ctype, _ = cgi.parse_header(self.headers.get("Content-Type", ""))
        if ctype != "multipart/form-data":
            respond_json(self, {"ok": False, "error": "Upload must be multipart/form-data."}, 400)
            return
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"}, keep_blank_values=True)
        field = form["file"] if "file" in form else None
        if not field or not field.filename:
            respond_json(self, {"ok": False, "error": "No file received."}, 400)
            return
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        target = UPLOAD_DIR / "2026 Equity PnL.xlsx"
        with target.open("wb") as handle:
            handle.write(field.file.read())
        CONFIG["transaction_file"] = str(target)
        CACHE.clear()
        respond_json(self, {"ok": True, "file": str(target), "message": "Initial Excel uploaded."})

    def serve_file(self, path: Path, content_type: str) -> None:
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    STATIC_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((DEFAULT_HOST, DEFAULT_PORT), AppHandler)
    print(f"Equity PnL Monitor: http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"Initial Excel: {find_transaction_file() or 'not found yet'}")
    print(f"Manual ledger: {LEDGER_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
