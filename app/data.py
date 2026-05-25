"""Thin wrapper around yfinance for daily OHLCV data.

We pull ~1 year of history (260 trading days) so we have enough room for
200-day moving averages and 252-day relative-strength windows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# Yahoo symbol for the Nifty 50 spot index (used as RS benchmark).
NIFTY_BENCHMARK = "^NSEI"


def fetch_history(ticker: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """Fetch daily OHLCV for a single ticker. Returns None on failure."""
    try:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        if df is None or df.empty:
            log.warning("No data for %s", ticker)
            return None
        # Normalize column names
        df = df.rename(columns=str.title)
        return df
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to fetch %s: %s", ticker, exc)
        return None


def fetch_benchmark(period: str = "1y") -> Optional[pd.DataFrame]:
    """Fetch Nifty 50 spot history for relative-strength calculations."""
    return fetch_history(NIFTY_BENCHMARK, period=period)


def latest_close(df: pd.DataFrame) -> float:
    return float(df["Close"].iloc[-1])


def next_earnings_days_away(ticker: str) -> Optional[int]:
    """Best-effort: days until next earnings announcement, or None if unknown.

    yfinance's `Ticker.calendar` is flaky and rate-limited, so callers should
    treat None as "unknown, allow trade" rather than hard-rejecting.
    """
    try:
        cal = yf.Ticker(ticker).calendar
        if not cal:
            return None
        # `calendar` may be a dict (newer yf) or a DataFrame (older yf).
        edate = None
        if isinstance(cal, dict):
            edate = cal.get("Earnings Date")
            if isinstance(edate, list) and edate:
                edate = edate[0]
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            val = cal.loc["Earnings Date"].iloc[0]
            edate = val
        if edate is None:
            return None
        if isinstance(edate, str):
            edate = datetime.fromisoformat(edate.split("T")[0])
        elif hasattr(edate, "to_pydatetime"):
            edate = edate.to_pydatetime()
        if not isinstance(edate, datetime):
            return None
        delta = (edate.date() - datetime.utcnow().date()).days
        return delta if delta >= 0 else None
    except Exception as exc:  # noqa: BLE001
        log.debug("Earnings lookup failed for %s: %s", ticker, exc)
        return None


def last_close_for_symbols(symbols: list[str]) -> dict[str, dict]:
    """Bulk fetch last close + 1-day pct change for a list of yfinance symbols.

    Used by the morning-brief endpoint.
    """
    out: dict[str, dict] = {}
    for sym in symbols:
        try:
            df = yf.Ticker(sym).history(period="5d", auto_adjust=False)
            if df is None or df.empty or len(df) < 2:
                out[sym] = {"price": None, "change_pct": None, "ts": None}
                continue
            last = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            chg = (last / prev - 1.0) * 100 if prev else None
            out[sym] = {
                "price": round(last, 2),
                "change_pct": round(chg, 2) if chg is not None else None,
                "ts": df.index[-1].isoformat(),
            }
        except Exception as exc:  # noqa: BLE001
            log.debug("Bulk fetch failed for %s: %s", sym, exc)
            out[sym] = {"price": None, "change_pct": None, "ts": None}
    return out
