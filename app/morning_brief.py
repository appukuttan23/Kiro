"""Premarket dashboard — pulls a quick snapshot of the macro indicators that
matter for Indian equity day-traders before the 9:15 AM IST open.

What we surface (all best-effort via yfinance — values may be `None` if the
provider rate-limits or temporarily fails to return data):

- Nifty 50 spot (^NSEI), India VIX (^INDIAVIX)
- USD/INR (INR=X), Brent crude (BZ=F), WTI (CL=F)
- US: S&P 500 (^GSPC), Dow (^DJI), Nasdaq (^IXIC)
- Asia/Globex: Nikkei 225 (^N225), Hang Seng (^HSI), GIFT Nifty proxy via ^NSEI

Each entry returns the last close, 1-day percent change, and timestamp.
The frontend reads this from `/api/morning-brief`.
"""
from __future__ import annotations

import logging
from typing import Any

from app.data import last_close_for_symbols

log = logging.getLogger(__name__)

# Group ticker -> human label so the UI can render it nicely
_INDIA: dict[str, str] = {
    "^NSEI": "Nifty 50 (spot)",
    "^INDIAVIX": "India VIX",
    "^BSESN": "Sensex",
    "INR=X": "USD/INR",
}

_COMMODITIES: dict[str, str] = {
    "BZ=F": "Brent Crude",
    "CL=F": "WTI Crude",
    "GC=F": "Gold (US$)",
}

_GLOBAL: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq",
    "^N225": "Nikkei 225",
    "^HSI": "Hang Seng",
}


def _interpret_vix(value: float | None) -> str:
    if value is None:
        return "data unavailable"
    if value < 13:
        return "complacent — be cautious of complacency reversals"
    if value < 18:
        return "normal range — risk-on environment"
    if value < 22:
        return "elevated — reduce position size"
    return "panic — stand aside or hedge"


def _interpret_inr(change_pct: float | None) -> str:
    if change_pct is None:
        return "data unavailable"
    if change_pct < -0.2:
        return "rupee strengthening (FII inflow signal)"
    if change_pct > 0.2:
        return "rupee weakening (FII outflow risk)"
    return "rupee stable"


def _interpret_brent(price: float | None) -> str:
    if price is None:
        return "data unavailable"
    if price < 80:
        return "oil cheap — bullish for India (oil importer)"
    if price < 90:
        return "neutral oil regime"
    if price < 100:
        return "oil elevated — watch CPI / fuel inflation"
    return "oil expensive — bearish for India macro"


def _build_section(syms: dict[str, str], data: dict[str, dict]) -> list[dict[str, Any]]:
    out = []
    for sym, label in syms.items():
        d = data.get(sym, {})
        out.append({
            "symbol": sym,
            "label": label,
            "price": d.get("price"),
            "change_pct": d.get("change_pct"),
            "ts": d.get("ts"),
        })
    return out


def fetch_morning_brief() -> dict[str, Any]:
    """Aggregate snapshot for the dashboard."""
    all_syms = list(_INDIA) + list(_COMMODITIES) + list(_GLOBAL)
    data = last_close_for_symbols(all_syms)

    india = _build_section(_INDIA, data)
    commodities = _build_section(_COMMODITIES, data)
    global_ = _build_section(_GLOBAL, data)

    # Headline interpretation
    vix = data.get("^INDIAVIX", {}).get("price")
    inr_chg = data.get("INR=X", {}).get("change_pct")
    brent = data.get("BZ=F", {}).get("price")

    interpretation = {
        "vix": _interpret_vix(vix),
        "inr": _interpret_inr(inr_chg),
        "brent": _interpret_brent(brent),
    }

    return {
        "india": india,
        "commodities": commodities,
        "global": global_,
        "interpretation": interpretation,
        "notes": [
            "GIFT Nifty pre-market level isn't on yfinance — check businesstoday.in or NDTV Profit between 8:00-9:00 AM IST.",
            "FII / DII provisional data is published on NSE around 6:00 PM IST after market close — track it manually.",
            "Avoid trading the first 15 minutes (9:15-9:30 AM IST) — opening volatility kills tight stops.",
        ],
    }
