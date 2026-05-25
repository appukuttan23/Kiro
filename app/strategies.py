"""Strategies inspired by legendary traders.

Existing:
  1. Minervini-Lite Trend Template          (Mark Minervini)
  2. Kotegawa 25-day Mean Reversion         (Takashi Kotegawa / BNF)

Added:
  3. Darvas Box Breakout                    (Nicolas Darvas)
  4. Turtle 20-day Donchian Breakout        (Richard Dennis / Turtles)
  5. Livermore Pivot Breakout               (Jesse Livermore)
  6. Zanger Volume Breakout                 (Dan Zanger)
  7. Qullamaggie Episodic Pivot             (Kristjan Kullamagi)

Each strategy is a function with the same signature:
    fn(ticker: str, df: pd.DataFrame) -> Optional[Signal]

It either returns a `Signal` (BUY candidate) or `None`. The scanner
(`app/main.py`) iterates over `ALL_STRATEGIES` and collects every Signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Signal:
    ticker: str
    strategy: str            # registry key, e.g. "darvas_box"
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


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range — Livermore-style volatility measure."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


# ============================================================
# Strategy 1: Minervini-Lite Trend Template
# ============================================================

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

    score = min((price / sma200) - 1.0, 0.50)
    pct_above_200 = (price / sma200 - 1) * 100

    reason = (
        f"In a healthy uptrend: price Rs.{price:.1f} is "
        f"{pct_above_200:.1f}% above the 200-day average, and the 50/150/200 "
        f"averages are stacked correctly (50>150>200). The long-term trend "
        f"is rising. Within 25% of its 52-week high (Rs.{high_52w:.1f})."
    )
    return Signal(ticker, "minervini_lite", "BUY", price, reason, score)


# ============================================================
# Strategy 2: Kotegawa / BNF 25-day Mean Reversion
# ============================================================

def kotegawa_meanrev(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Buy-the-dip on oversold pullbacks.

    Checks (all must be true):
      A. Price is at least 5% below the 25-day SMA
      B. RSI(14) < 30
      C. The stock is in a long-term uptrend (price > 200-day SMA)
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

    score = abs(deviation) + (30 - float(rsi)) / 100

    reason = (
        f"Oversold dip in an uptrend: price Rs.{price:.1f} is "
        f"{abs(deviation) * 100:.1f}% below the 25-day average (Rs.{sma25:.1f}), "
        f"RSI is {float(rsi):.0f} (oversold), but price is still above the "
        f"200-day average (Rs.{sma200:.1f}) - a possible bounce setup."
    )
    return Signal(ticker, "kotegawa_meanrev", "BUY", price, reason, score)


# ============================================================
# Strategy 3: Darvas Box Breakout (Nicolas Darvas)
# ============================================================

def darvas_box(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Break out of a tight consolidation box to a new high.

    Darvas waited for a stock to make a new high, then watched it form a
    "box" - oscillating in a tight range for several days/weeks. He bought
    when price broke ABOVE the top of that box.

    Checks:
      A. Today's close >= 52-week high (or within 0.5% of it).
      B. Box was tight: highest high of prior 20 trading days
         (excluding today) was within 8% of its lowest low - a real
         consolidation, not a trend that just kept rising.
      C. Today's close is ABOVE the top of that prior box (true breakout).
      D. Price is above the 50-day SMA (uptrend filter).
    """
    if len(df) < 252:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    price = float(close.iloc[-1])

    sma50 = _sma(close, 50).iloc[-1]
    if pd.isna(sma50):
        return None

    high_52w = float(high.iloc[-252:].max())

    # Prior 20-day box (excluding today)
    box_high = float(high.iloc[-21:-1].max())
    box_low = float(low.iloc[-21:-1].min())
    if box_low <= 0:
        return None
    box_range_pct = (box_high - box_low) / box_low

    cond_a = price >= 0.995 * high_52w
    cond_b = box_range_pct <= 0.08              # tight box (<= 8% range)
    cond_c = price > box_high                   # genuine breakout
    cond_d = price > sma50

    if not (cond_a and cond_b and cond_c and cond_d):
        return None

    breakout_pct = (price / box_high - 1) * 100
    # Tighter box + stronger breakout = higher score
    score = (1 - box_range_pct / 0.08) * 0.5 + min(breakout_pct / 5.0, 0.5)

    reason = (
        f"Darvas box breakout: stock spent the last 20 days in a tight range "
        f"of just {box_range_pct * 100:.1f}% (Rs.{box_low:.1f}-{box_high:.1f}), "
        f"and today's close of Rs.{price:.1f} broke ABOVE the box top by "
        f"{breakout_pct:.1f}%, making a fresh 52-week high. Stop-loss "
        f"suggestion: just below the box top (Rs.{box_high:.1f})."
    )
    return Signal(ticker, "darvas_box", "BUY", price, reason, score)


# ============================================================
# Strategy 4: Turtle 20-day Donchian Breakout (Richard Dennis)
# ============================================================

def turtle_breakout(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Classic Turtle Trader 'System 1' entry.

    Donchian channel breakout: buy when today's close breaks ABOVE the
    highest high of the prior 20 trading days. Famous for trend-following
    futures, but works on equities too.

    Checks:
      A. Close > highest high of prior 20 days (excl. today).
      B. Price > 50-day SMA AND 50-SMA > 200-SMA (uptrend filter to avoid
         whipsaws in downtrends - the original Turtle rules used a
         separate filter system; we keep it simple).
      C. ATR(14) is finite (used for stop-loss suggestion).
    """
    if len(df) < 220:
        return None

    close = df["Close"]
    high = df["High"]
    price = float(close.iloc[-1])

    prior_high_20 = float(high.iloc[-21:-1].max())
    sma50 = _sma(close, 50).iloc[-1]
    sma200 = _sma(close, 200).iloc[-1]
    atr = _atr(df, 14).iloc[-1]

    if any(pd.isna(x) for x in (sma50, sma200, atr)):
        return None

    cond_a = price > prior_high_20
    cond_b = price > sma50 and sma50 > sma200
    cond_c = atr > 0

    if not (cond_a and cond_b and cond_c):
        return None

    breakout_pct = (price / prior_high_20 - 1) * 100
    # Original Turtles used a 2N (2 x ATR) initial stop
    suggested_stop = price - 2 * float(atr)
    score = min(breakout_pct / 5.0, 1.0)

    reason = (
        f"Turtle 20-day breakout: today's close of Rs.{price:.1f} broke "
        f"above the highest high of the last 20 days (Rs.{prior_high_20:.1f}) "
        f"by {breakout_pct:.1f}%, while in a confirmed uptrend "
        f"(50-SMA > 200-SMA). Turtle-style stop: Rs.{suggested_stop:.1f} "
        f"(2 x ATR below entry, ATR=Rs.{float(atr):.1f})."
    )
    return Signal(ticker, "turtle_breakout", "BUY", price, reason, score)


# ============================================================
# Strategy 5: Livermore Pivot Breakout (Jesse Livermore)
# ============================================================

def livermore_pivot(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Break above a prior pivot high on confirming volume.

    Livermore watched for a stock to test a prior resistance ("pivot point")
    multiple times, then bought the breakout when volume confirmed it -
    his 'line of least resistance' principle.

    Checks:
      A. Identify the prior pivot: highest high in the window from 60 to
         10 days ago. (Excludes the most recent 10 days so we capture an
         OLDER resistance level being tested today.)
      B. Today's close breaks above that pivot.
      C. Today's volume is at least 1.5x the 50-day average volume
         (Livermore's volume-confirmation rule).
      D. Stock is in a long-term uptrend (close > 200-SMA).
    """
    if len(df) < 220 or "Volume" not in df.columns:
        return None

    close = df["Close"]
    high = df["High"]
    volume = df["Volume"]
    price = float(close.iloc[-1])

    pivot = float(high.iloc[-60:-10].max())     # older resistance
    sma200 = _sma(close, 200).iloc[-1]
    avg_vol_50 = float(volume.iloc[-50:].mean())
    today_vol = float(volume.iloc[-1])

    if pd.isna(sma200) or avg_vol_50 <= 0:
        return None

    vol_multiple = today_vol / avg_vol_50

    cond_a = price > pivot
    cond_b = vol_multiple >= 1.5
    cond_c = price > sma200

    if not (cond_a and cond_b and cond_c):
        return None

    breakout_pct = (price / pivot - 1) * 100
    # Score: prefer modest breakouts on strong volume (avoid blow-offs)
    score = min(breakout_pct / 4.0, 0.6) + min((vol_multiple - 1.5) / 3.0, 0.4)

    reason = (
        f"Livermore pivot breakout: price Rs.{price:.1f} broke above the "
        f"prior resistance pivot at Rs.{pivot:.1f} (the high of the last "
        f"60 days, formed before the recent base) by {breakout_pct:.1f}%. "
        f"Volume confirmed at {vol_multiple:.1f}x the 50-day average, "
        f"in a long-term uptrend. Stop-loss: just below Rs.{pivot:.1f} "
        f"(prior resistance now becomes support)."
    )
    return Signal(ticker, "livermore_pivot", "BUY", price, reason, score)


# ============================================================
# Strategy 6: Zanger Volume Breakout (Dan Zanger)
# ============================================================

def zanger_breakout(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Tight base + 2x volume breakout in a momentum leader.

    Dan Zanger's record-breaking returns came from explosive breakouts of
    stocks already showing relative strength. The setup:

      A. The stock is a momentum leader: up at least 30% over the past
         year (relative-strength proxy).
      B. The last ~40 trading days (~2 months) formed a tight base:
         range from low-to-high <= 15%.
      C. Today's close breaks above the base high (new local high).
      D. Today's volume is at least 2x the 50-day average volume.
    """
    if len(df) < 252 or "Volume" not in df.columns:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    price = float(close.iloc[-1])

    price_1y_ago = float(close.iloc[-252])
    if price_1y_ago <= 0:
        return None
    one_year_return = price / price_1y_ago - 1

    # Base = prior 40 days, excluding today
    base_high = float(high.iloc[-41:-1].max())
    base_low = float(low.iloc[-41:-1].min())
    if base_low <= 0:
        return None
    base_range = (base_high - base_low) / base_low

    avg_vol_50 = float(volume.iloc[-50:].mean())
    today_vol = float(volume.iloc[-1])
    if avg_vol_50 <= 0:
        return None
    vol_multiple = today_vol / avg_vol_50

    cond_a = one_year_return >= 0.30
    cond_b = base_range <= 0.15
    cond_c = price > base_high
    cond_d = vol_multiple >= 2.0

    if not (cond_a and cond_b and cond_c and cond_d):
        return None

    breakout_pct = (price / base_high - 1) * 100
    score = min(vol_multiple / 5.0, 0.5) + min(one_year_return / 1.0, 0.5)

    reason = (
        f"Zanger-style breakout: stock is a momentum leader (up "
        f"{one_year_return * 100:.0f}% in the past year), spent the last "
        f"~2 months in a tight base ({base_range * 100:.1f}% range, "
        f"Rs.{base_low:.1f}-{base_high:.1f}), and today broke above the "
        f"base high to Rs.{price:.1f} (+{breakout_pct:.1f}%) on "
        f"{vol_multiple:.1f}x average volume. Stop-loss: below the "
        f"base high (Rs.{base_high:.1f})."
    )
    return Signal(ticker, "zanger_breakout", "BUY", price, reason, score)


# ============================================================
# Strategy 7: Qullamaggie Episodic Pivot (Kristjan Kullamagi)
# ============================================================

def qullamaggie_ep(ticker: str, df: pd.DataFrame) -> Optional[Signal]:
    """Big gap-up after a strong multi-month move.

    Qullamaggie's "episodic pivot" trade looks for a stock that has
    already had a strong run (3-6 months of momentum), then has a
    catalyst day - a big gap up on huge volume - which often kicks
    off the next leg higher.

    Checks:
      A. Strong prior momentum: up at least 20% over the past 3 months.
      B. Today is a "pivot day": gap-up of at least 4% (today's open
         vs. yesterday's close) AND today closes near the high
         (close >= open + 0.7 * (high - open)) - i.e. the gap held.
      C. Volume at least 2x the 50-day average.
      D. Above all major moving averages (10, 20, 50-day).
    """
    if len(df) < 220 or "Volume" not in df.columns:
        return None

    close = df["Close"]
    open_ = df["Open"]
    high = df["High"]
    volume = df["Volume"]
    price = float(close.iloc[-1])

    today_open = float(open_.iloc[-1])
    today_high = float(high.iloc[-1])
    prev_close = float(close.iloc[-2])
    if prev_close <= 0:
        return None

    price_3m_ago = float(close.iloc[-63])       # ~3 months
    if price_3m_ago <= 0:
        return None
    three_month_return = price / price_3m_ago - 1

    gap_pct = (today_open / prev_close) - 1

    # Closed in the upper portion of today's range (gap held)
    intraday_range = today_high - today_open
    held_gap = (
        intraday_range <= 0
        or (price - today_open) >= 0.7 * intraday_range
    )

    sma10 = _sma(close, 10).iloc[-1]
    sma20 = _sma(close, 20).iloc[-1]
    sma50 = _sma(close, 50).iloc[-1]
    if any(pd.isna(x) for x in (sma10, sma20, sma50)):
        return None

    avg_vol_50 = float(volume.iloc[-50:].mean())
    today_vol = float(volume.iloc[-1])
    if avg_vol_50 <= 0:
        return None
    vol_multiple = today_vol / avg_vol_50

    cond_a = three_month_return >= 0.20
    cond_b = gap_pct >= 0.04 and held_gap
    cond_c = vol_multiple >= 2.0
    cond_d = price > sma10 and price > sma20 and price > sma50

    if not (cond_a and cond_b and cond_c and cond_d):
        return None

    score = (
        min(gap_pct / 0.10, 0.4)
        + min(vol_multiple / 5.0, 0.3)
        + min(three_month_return / 0.50, 0.3)
    )

    reason = (
        f"Episodic pivot (Qullamaggie): stock is up "
        f"{three_month_return * 100:.0f}% over the last 3 months, gapped "
        f"up {gap_pct * 100:.1f}% today, held the gap into the close at "
        f"Rs.{price:.1f}, on {vol_multiple:.1f}x average volume. Above "
        f"the 10/20/50-day averages. Tight stop suggestion: today's low."
    )
    return Signal(ticker, "qullamaggie_ep", "BUY", price, reason, score)


# ---------- registry ----------

ALL_STRATEGIES = {
    "minervini_lite":   minervini_lite,
    "kotegawa_meanrev": kotegawa_meanrev,
    "darvas_box":       darvas_box,
    "turtle_breakout":  turtle_breakout,
    "livermore_pivot":  livermore_pivot,
    "zanger_breakout":  zanger_breakout,
    "qullamaggie_ep":   qullamaggie_ep,
}
