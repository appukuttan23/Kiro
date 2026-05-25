"""Two beginner-friendly strategies.

1. Minervini-Lite Trend Template
   A simplified version of Mark Minervini's 8-point Trend Template, focused on
   the most important moving-average alignment checks. Identifies stocks in
   a healthy long-term uptrend.

2. Kotegawa 25-day Mean Reversion
   Inspired by Takashi Kotegawa (BNF). Looks for stocks that have dropped
   significantly below their 25-day SMA AND are oversold by RSI. The
   hypothesis: short-term panic; price tends to revert toward the mean.

Each strategy returns either a `Signal` dataclass or `None`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Signal:
    ticker: str
    strategy: str            # "minervini_lite" | "kotegawa_meanrev"
    action: str              # "BUY"
    price: float
    reason: str              # Plain-English explanation
    score: float             # Higher = stronger setup, for sorting


# ---------- helpers ----------

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ---------- Strategy 1: Minervini-Lite Trend Template ----------

def minervini_lite(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Long-term trend filter.

    Checks (all must be true):
      A. Price > 50, 150, 200-day SMA
      B. 50 SMA > 150 SMA > 200 SMA
      C. 200 SMA is rising (today > 1 month ago)
      D. Price within 25% of 52-week high (i.e. not a beaten-down stock)
    """
    if len(df) < 220:
        return None

    close = df["Close"]
    price = float(close.iloc[-1])

    sma50 = _sma(close, 50).iloc[-1]
    sma150 = _sma(close, 150).iloc[-1]
    sma200 = _sma(close, 200).iloc[-1]
    sma200_prev = _sma(close, 200).iloc[-21] if len(df) > 220 else np.nan

    if any(pd.isna(x) for x in (sma50, sma150, sma200, sma200_prev)):
        return None

    high_52w = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())

    cond_a = price > sma50 and price > sma150 and price > sma200
    cond_b = sma50 > sma150 > sma200
    cond_c = sma200 > sma200_prev
    cond_d = price >= 0.75 * high_52w

    if not (cond_a and cond_b and cond_c and cond_d):
        return None

    # Score: how far above the 200-SMA? (capped)
    score = min((price / sma200) - 1.0, 0.50)
    pct_above_200 = (price / sma200 - 1) * 100

    reason = (
        f"In a healthy uptrend: price ₹{price:.1f} is "
        f"{pct_above_200:.1f}% above the 200-day average, and the 50/150/200 "
        f"averages are stacked correctly (50>150>200). The long-term trend "
        f"is rising. Within 25% of its 52-week high (₹{high_52w:.1f})."
    )
    return Signal(ticker, "minervini_lite", "BUY", price, reason, score)


# ---------- Strategy 2: Kotegawa 25-day Mean Reversion ----------

def kotegawa_meanrev(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Buy-the-dip on oversold pullbacks.

    Checks (all must be true):
      A. Price is at least 5% below the 25-day SMA
      B. RSI(14) < 30
      C. The stock is in a long-term uptrend (price > 200-day SMA) so we
         buy dips in uptrends, not falling knives.
    """
    if len(df) < 210:
        return None

    close = df["Close"]
    price = float(close.iloc[-1])
    sma25 = _sma(close, 25).iloc[-1]
    sma200 = _sma(close, 200).iloc[-1]
    rsi = _rsi(close, 14).iloc[-1]

    if any(pd.isna(x) for x in (sma25, sma200, rsi)):
        return None

    deviation = (price / sma25) - 1.0  # negative means below 25-SMA

    cond_a = deviation <= -0.05
    cond_b = rsi < 30
    cond_c = price > sma200  # uptrend filter

    if not (cond_a and cond_b and cond_c):
        return None

    # Score: deeper dip + lower RSI = stronger setup
    score = abs(deviation) + (30 - float(rsi)) / 100

    reason = (
        f"Oversold dip in an uptrend: price ₹{price:.1f} is "
        f"{abs(deviation) * 100:.1f}% below the 25-day average (₹{sma25:.1f}), "
        f"RSI is {float(rsi):.0f} (oversold), but price is still above the "
        f"200-day average (₹{sma200:.1f}) — a possible bounce setup."
    )
    return Signal(ticker, "kotegawa_meanrev", "BUY", price, reason, score)


# ---------- registry ----------

ALL_STRATEGIES = {
    "minervini_lite": minervini_lite,
    "kotegawa_meanrev": kotegawa_meanrev,
}
