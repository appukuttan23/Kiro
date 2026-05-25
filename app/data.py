"""Thin wrapper around yfinance for daily OHLCV data.

We pull ~1 year of history (260 trading days) so we have enough room for
200-day moving averages.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)


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


def latest_close(df: pd.DataFrame) -> float:
    return float(df["Close"].iloc[-1])
