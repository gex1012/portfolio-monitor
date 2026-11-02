"""Industry exposure from current USD position values, independent of price history."""
from typing import Any

import numpy as np
import pandas as pd


SECTORS = {
    "Energy": "能源", "Technology": "信息技术", "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "必需消费", "Communication Services": "通信服务",
    "Industrials": "工业", "Basic Materials": "原材料", "Financial Services": "金融",
    "Healthcare": "医疗保健", "Real Estate": "房地产", "Utilities": "公用事业",
}
INDUSTRIES = {
    "Semiconductors": "半导体", "Oil & Gas Integrated": "综合油气",
    "Uranium": "铀矿与核燃料", "Oil & Gas Exploration & Production": "油气勘探与开采",
    "Oil & Gas Midstream": "油气中游与 LNG", "Specialty Retail": "专业零售与电商",
    "Hardware, Equipment & Parts": "电子硬件与光通信设备",
    "Internet Content & Information": "互联网内容与信息服务",
    "Oil & Gas Equipment & Services": "油气设备与服务",
    "Electrical Equipment & Parts": "电气设备与零部件", "Auto - Parts": "汽车零部件",
    "Oil & Gas Drilling": "油气钻井", "Asset Management": "资产管理",
}

# Verified FMP profile snapshot, 2026-11-02; used only when a live profile is missing.
PROFILE_FALLBACKS = {
    "MRVL": ("Technology", "Semiconductors"),
    "0386.HK": ("Energy", "Oil & Gas Integrated"),
    "CCJ": ("Energy", "Uranium"),
    "EQT": ("Energy", "Oil & Gas Exploration & Production"),
    "AVGO": ("Technology", "Semiconductors"),
    "LNG": ("Energy", "Oil & Gas Midstream"),
    "9988.HK": ("Consumer Cyclical", "Specialty Retail"),
    "COHR": ("Technology", "Hardware, Equipment & Parts"),
    "AMZN": ("Consumer Cyclical", "Specialty Retail"),
    "GOOG": ("Communication Services", "Internet Content & Information"),
    "SLB": ("Energy", "Oil & Gas Equipment & Services"),
    "VRT": ("Industrials", "Electrical Equipment & Parts"),
    "2338.HK": ("Consumer Cyclical", "Auto - Parts"),
    "AMAT": ("Technology", "Semiconductors"),
    "SDRL": ("Energy", "Oil & Gas Drilling"),
}
ETF_EXPOSURES = {
    "SOXX": ("信息技术", "半导体 ETF", "https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf"),
    "WEAT": ("商品", "农业商品 / 小麦期货 ETF", "https://teucrium.com/WEAT"),
}


def classify_security(symbol: str, profile: Any = None) -> dict[str, str]:
    symbol = symbol.strip().upper()
    if symbol in ETF_EXPOSURES:
        sector, industry, url = ETF_EXPOSURES[symbol]
        return {"sector": sector, "industry": industry, "instrument": "ETF",
                "classification_source": "发行商资料", "source_url": url}
    profile = profile if isinstance(profile, dict) else {}
    # Do not classify funds by the fund manager's corporate sector.
    if profile.get("isEtf") is True or profile.get("isFund") is True:
        return {"sector": "基金 / 待穿透", "industry": "基金 / 待穿透", "instrument": "ETF / 基金",
                "classification_source": "FMP（投向待核实）", "source_url": ""}
    sector = str(profile.get("sector") or "").strip()
    industry = str(profile.get("industry") or "").strip()
    source = "FMP"
    if not sector:
        sector, industry = PROFILE_FALLBACKS.get(symbol, ("", ""))
        source = "FMP 备用资料（2026-11-02）" if sector else "待核实"
    return {"sector": SECTORS.get(sector, sector or "未分类"),
            "industry": INDUSTRIES.get(industry, industry or "未分类"),
            "instrument": "股票", "classification_source": source, "source_url": ""}


def build_industry_allocation(holdings: list[dict[str, Any]], classifications: dict[str, dict[str, str]],
                              *, broker: str | None = None, nav: float = 0.0,
                              level: str = "sector") -> dict[str, Any]:
    frame = pd.DataFrame(holdings)
    if frame.empty:
        return {"ok": False}
    frame = frame.copy()
    frame["broker"] = frame.get("broker", pd.Series("国投", index=frame.index)).fillna("国投").replace("", "国投")
    if broker:
        frame = frame[frame["broker"] == broker].copy()
    for key in ["quantity", "market_value_usd", "unrealized_pnl_usd"]:
        frame[key] = pd.to_numeric(frame.get(key, pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
        frame[key] = frame[key].replace([np.inf, -np.inf], 0.0)
    frame = frame[(frame["quantity"].abs() > 1e-9) & (frame["market_value_usd"].abs() > 0)].copy()
    if frame.empty:
        return {"ok": False}
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["gross_value_usd"] = frame["market_value_usd"].abs()
    # Combine the same ticker across brokers; keep gross exposures if long/short offset.
    positions = frame.groupby("symbol", as_index=False).agg(
        quantity=("quantity", "sum"), market_value_usd=("market_value_usd", "sum"),
        gross_value_usd=("gross_value_usd", "sum"), unrealized_pnl_usd=("unrealized_pnl_usd", "sum"),
        broker=("broker", lambda values: " / ".join(sorted(set(values)))),
    )
    for key in ["sector", "industry", "instrument", "classification_source"]:
        positions[key] = positions["symbol"].map(
            lambda symbol: classifications.get(symbol, classify_security(symbol)).get(key, "未分类"))
    total = float(positions["gross_value_usd"].sum())
    positions["weight"] = positions["gross_value_usd"] / total
    category = "industry" if level == "industry" else "sector"
    summary = positions.groupby(category, as_index=False).agg(
        market_value_usd=("market_value_usd", "sum"), gross_value_usd=("gross_value_usd", "sum"),
        unrealized_pnl_usd=("unrealized_pnl_usd", "sum"), stock_count=("symbol", "nunique"),
        symbols=("symbol", lambda values: " / ".join(sorted(values))),
    ).rename(columns={category: "category"})
    summary["weight"] = summary["gross_value_usd"] / total
    summary["nav_weight"] = summary["market_value_usd"] / nav if nav > 0 else np.nan
    return {"ok": True, "summary": summary.sort_values("gross_value_usd", ascending=False).reset_index(drop=True),
            "positions": positions.sort_values("gross_value_usd", ascending=False),
            "gross_value_usd": total, "has_shorts": bool((frame["market_value_usd"] < 0).any()),
            "unknown_value_usd": float(positions.loc[positions["sector"].isin(["未分类", "基金 / 待穿透"]), "gross_value_usd"].sum())}
