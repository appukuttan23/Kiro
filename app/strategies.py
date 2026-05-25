"""Daily-timeframe scanning strategies for the Indian equity universe.

Three pillars are implemented:

1. **Minervini-Lite Trend Template** — momentum / trend-following.
   A simplified version of Mark Minervini's 8-point Trend Template, focused on
   moving-average alignment, plus volume thrust + relative strength to weed
   out lifeless uptrends.

2. **Kotegawa 25-day Mean Reversion** — buy-the-dip in an uptrend.
   Inspired by Takashi Kotegawa (BNF). Looks for stocks that have dropped
   significantly below their 25-day SMA AND are oversold by RSI, while still
   being above their 200-day SMA (no falling knives).

3. **Darvas / 52-Week-High Breakout** — pattern-based momentum.
   Inspired by Nicolas Darvas. Looks for stocks breaking out to a fresh
   52-week high after a tight consolidation (Darvas box), confirmed by
   above-average volume.

Each strategy returns either a `Signal` dataclass or `None`.

Caller can additionally pass a `benchmark_df` (Nifty 50 daily history) to
enable relative-strength filtering, and `earnings_days_away` to optionally
warn about upcoming earnings (does NOT hard-reject — earnings data is flaky).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Signal:
    ticker: str
    strategy: str            # "minervini_lite" | "kotegawa_meanrev" | "darvas_breakout"
    action: str              # "BUY"
    price: float
    reason: str              # Plain-English explanation
    score: float             # Higher = stronger setup, for sorting
    warnings: list[str] = field(default_factory=list)  # Soft warnings (e.g. earnings)


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

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


def _volume_thrust(df: pd.DataFrame, mult: float = 1.5, lookback: int = 20) -> Optional[float]:
    """Today's volume / average volume over `lookback` days.

    Returns the multiple (e.g. 1.85x) or None if volume data is unavailable.
    Caller decides whether `multiple >= mult` is required.
    """
    if "Volume" not in df.columns or len(df) < lookback + 1:
        return None
    today = float(df["Volume"].iloc[-1])
    avg = float(df["Volume"].iloc[-lookback - 1: -1].mean())
    if avg <= 0:
        return None
    return today / avg


def _relative_strength(stock_df: pd.DataFrame,
                        benchmark_df: Optional[pd.DataFrame],
                        lookback: int = 63) -> Optional[float]:
    """Stock return minus benchmark return over `lookback` trading days (default 3M).

    Positive = outperforming. None if benchmark not provided or insufficient data.
    """
    if benchmark_df is None or len(stock_df) < lookback + 1 or len(benchmark_df) < lookback + 1:
        return None
    s_ret = stock_df["Close"].iloc[-1] / stock_df["Close"].iloc[-lookback - 1] - 1
    b_ret = benchmark_df["Close"].iloc[-1] / benchmark_df["Close"].iloc[-lookback - 1] - 1
    return float(s_ret - b_ret)


def _distance_from_high(close: pd.Series, lookback: int = 252) -> float:
    """How close (as a fraction) price is to its lookback-day high.
    1.0 = at the high, 0.0 = price is zero. Used as a quality filter.
    """
    window = close.iloc[-lookback:] if len(close) >= lookback else close
    high = float(window.max())
    if high <= 0:
        return 0.0
    return float(close.iloc[-1] / high)


def _earnings_warning(days_away: Optional[int]) -> Optional[str]:
    """Return a soft warning string if earnings is within 3 trading days."""
    if days_away is None:
        return None
    if 0 <= days_away <= 3:
        return f"Earnings announcement in ~{days_away} day(s) — consider reducing size or waiting."
    return None


# ---------------------------------------------------------------------------
# Strategy 1: Minervini-Lite Trend Template
# ---------------------------------------------------------------------------

def minervini_lite(ticker: str,
                   df: pd.DataFrame,
                   benchmark_df: Optional[pd.DataFrame] = None,
                   earnings_days_away: Optional[int] = None) -> Optional[Signal]:
    """Long-term trend filter with quality screens.

    Hard requirements (all must be true):
      A. Price > 50, 150, 200-day SMA
      B. 50 SMA > 150 SMA > 200 SMA
      C. 200 SMA is rising (today > 1 month ago)
      D. Price within 25% of 52-week high (i.e. not a beaten-down stock)
      E. Volume in last 5 days at least 1.2x its 20-day average
         (cheap proxy for institutional accumulation)

    Soft preference (boosts score, not required):
      F. Outperforming Nifty over the last 63 trading days (~3 months)
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

    # Volume thrust over last 5 days vs 20-day baseline
    if "Volume" in df.columns and len(df) >= 25:
        recent_vol = float(df["Volume"].iloc[-5:].mean())
        base_vol = float(df["Volume"].iloc[-25:-5].mean())
        if base_vol <= 0 or recent_vol < 1.2 * base_vol:
            return None
        vol_mult = recent_vol / base_vol
    else:
        vol_mult = None

    rs = _relative_strength(df, benchmark_df, lookback=63)

    # Score: weighted blend of distance above 200-SMA, volume thrust, RS
    base_score = min((price / sma200) - 1.0, 0.50)
    vol_bonus = 0.0 if vol_mult is None else min((vol_mult - 1.2) * 0.10, 0.10)
    rs_bonus = 0.0 if rs is None else max(min(rs, 0.20), -0.10)
    score = base_score + vol_bonus + rs_bonus

    pct_above_200 = (price / sma200 - 1) * 100
    rs_str = f", outperforming Nifty by {rs * 100:+.1f}% over 3M" if rs is not None else ""
    vol_str = f", recent volume {vol_mult:.1f}x its 20-day average" if vol_mult else ""

    reason = (
        f"In a healthy uptrend: price ₹{price:.1f} is "
        f"{pct_above_200:.1f}% above the 200-day average, with the 50/150/200 "
        f"averages stacked correctly (50>150>200) and 200-SMA rising. "
        f"Within 25% of its 52-week high (₹{high_52w:.1f}){vol_str}{rs_str}."
    )

    sig = Signal(ticker, "minervini_lite", "BUY", price, reason, score)
    if (w := _earnings_warning(earnings_days_away)):
        sig.warnings.append(w)
    return sig


# ---------------------------------------------------------------------------
# Strategy 2: Kotegawa 25-day Mean Reversion
# ---------------------------------------------------------------------------

def kotegawa_meanrev(ticker: str,
                     df: pd.DataFrame,
                     benchmark_df: Optional[pd.DataFrame] = None,
                     earnings_days_away: Optional[int] = None) -> Optional[Signal]:
    """Buy-the-dip on oversold pullbacks in an uptrend.

    Hard requirements (all must be true):
      A. Price is at least 5% below the 25-day SMA
      B. RSI(14) < 30
      C. Price > 200-day SMA  (only buy dips inside an uptrend)
      D. Stock is not significantly underperforming Nifty over 6M
         (RS_126 > -10%) — keeps falling-knife stocks out
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
    cond_c = price > sma200

    if not (cond_a and cond_b and cond_c):
        return None

    rs_6m = _relative_strength(df, benchmark_df, lookback=126)
    if rs_6m is not None and rs_6m < -0.10:
        # Stock has been a chronic underperformer — likely a falling knife
        return None

    # Score: deeper dip + lower RSI = stronger setup
    score = abs(deviation) + (30 - float(rsi)) / 100
    rs_str = f"; RS vs Nifty over 6M: {rs_6m * 100:+.1f}%" if rs_6m is not None else ""

    reason = (
        f"Oversold dip in an uptrend: price ₹{price:.1f} is "
        f"{abs(deviation) * 100:.1f}% below the 25-day average (₹{sma25:.1f}), "
        f"RSI is {float(rsi):.0f} (oversold), but price is still above the "
        f"200-day average (₹{sma200:.1f}) — possible bounce setup{rs_str}."
    )

    sig = Signal(ticker, "kotegawa_meanrev", "BUY", price, reason, score)
    if (w := _earnings_warning(earnings_days_away)):
        sig.warnings.append(w)
    return sig


# ---------------------------------------------------------------------------
# Strategy 3: Darvas / 52-Week-High Breakout
# ---------------------------------------------------------------------------

def darvas_breakout(ticker: str,
                    df: pd.DataFrame,
                    benchmark_df: Optional[pd.DataFrame] = None,
                    earnings_days_away: Optional[int] = None) -> Optional[Signal]:
    """Fresh 52-week-high breakout from a tight base.

    Hard requirements (all must be true):
      A. Today's close is the highest in the last 252 trading days
      B. Prior 20-day range was tight: (high - low) / low <= 15%  (consolidation)
      C. Today's volume >= 1.5x of the 20-day average  (real breakout, not drift)
      D. Price > 50-day SMA  (avoid bear-market pops)
    """
    if len(df) < 252:
        return None

    close = df["Close"]
    high = df.get("High", close)
    low = df.get("Low", close)
    price = float(close.iloc[-1])

    # A. New 252-day high (today is the max)
    high_252 = float(close.iloc[-252:].max())
    if price < high_252 * 0.999:  # tiny tolerance for float math
        return None

    # B. Prior 20 days were a tight consolidation (use last 21 days excluding today)
    prior = close.iloc[-21:-1]
    prior_high = float(prior.max())
    prior_low = float(prior.min())
    if prior_low <= 0:
        return None
    range_pct = (prior_high - prior_low) / prior_low
    if range_pct > 0.15:
        return None

    # C. Volume thrust today vs 20-day average
    vol_mult = _volume_thrust(df, mult=1.5, lookback=20)
    if vol_mult is None or vol_mult < 1.5:
        return None

    # D. Above 50-day SMA
    sma50 = _sma(close, 50).iloc[-1]
    if pd.isna(sma50) or price <= sma50:
        return None

    rs_3m = _relative_strength(df, benchmark_df, lookback=63)

    # Score: tighter prior range + bigger volume thrust + RS = stronger breakout
    tightness_bonus = max(0.0, (0.15 - range_pct))           # up to 0.15
    volume_bonus = min((vol_mult - 1.5) * 0.10, 0.20)        # up to 0.20
    rs_bonus = 0.0 if rs_3m is None else max(min(rs_3m, 0.20), -0.10)
    score = 0.20 + tightness_bonus + volume_bonus + rs_bonus

    rs_str = f", outperforming Nifty by {rs_3m * 100:+.1f}% over 3M" if rs_3m is not None else ""

    reason = (
        f"Breakout to a fresh 52-week high (₹{price:.1f}) on "
        f"{vol_mult:.1f}x volume after a tight {range_pct * 100:.1f}% range "
        f"over the last 20 days{rs_str}. Classic Darvas-box setup."
    )

    sig = Signal(ticker, "darvas_breakout", "BUY", price, reason, score)
    if (w := _earnings_warning(earnings_days_away)):
        sig.warnings.append(w)
    return sig


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_STRATEGIES = {
    "minervini_lite": minervini_lite,
    "kotegawa_meanrev": kotegawa_meanrev,
    "darvas_breakout": darvas_breakout,
}
