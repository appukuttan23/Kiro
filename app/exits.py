"""Exit rules - one per entry strategy.

Every entry strategy in app/strategies.py has a paired exit rule here.
The scheduler calls `check_exits_for_open_trades()` every daily scan and
collects SELL alerts that surface alongside BUY alerts in the report.

Each exit function has the same signature:
    fn(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]

`trade` is a paper-trade record (has 'price' = entry, 'ts' = entry timestamp,
'strategy', 'qty', 'ticker'). `df` is current daily OHLCV history.

Three exit types:
    "TARGET"      - take profit
    "STOP"        - cut losses
    "TIME"        - didn't work in time
    "TREND_BREAK" - the original trend that justified entry has reversed
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app.strategies import _atr, _sma


@dataclass
class ExitSignal:
    trade_id: str
    ticker: str
    strategy: str
    action: str          # always "SELL"
    exit_type: str       # "TARGET" | "STOP" | "TIME" | "TREND_BREAK"
    entry_price: float
    current_price: float
    pnl_pct: float
    qty: int
    reason: str
    score: float         # urgency: STOP=1.0, TREND_BREAK=0.9, TARGET=0.7, TIME=0.5


# ---------- helpers ----------

def _days_held(trade: dict) -> int:
    ts = trade.get("ts", "")
    try:
        # stored as ISO with trailing 'Z'
        entry_dt = datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return 0
    return max(0, (datetime.now(timezone.utc) - entry_dt).days)


def _make_exit(
    trade: dict,
    df: pd.DataFrame,
    exit_type: str,
    reason: str,
    score: float,
) -> ExitSignal:
    current = float(df["Close"].iloc[-1])
    entry = float(trade["price"])
    pnl_pct = (current / entry - 1) * 100 if entry > 0 else 0.0
    return ExitSignal(
        trade_id=trade["id"],
        ticker=trade["ticker"],
        strategy=trade.get("strategy", "unknown"),
        action="SELL",
        exit_type=exit_type,
        entry_price=entry,
        current_price=current,
        pnl_pct=round(pnl_pct, 2),
        qty=int(trade.get("qty", 0)),
        reason=reason,
        score=score,
    )


# ============================================================
# Per-strategy exit rules
# ============================================================

def exit_minervini_lite(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Exit when the trend is broken: close < 50-day SMA."""
    if len(df) < 50:
        return None
    close = df["Close"]
    price = float(close.iloc[-1])
    sma50 = _sma(close, 50).iloc[-1]
    if pd.isna(sma50):
        return None
    if price < float(sma50):
        return _make_exit(
            trade, df, "TREND_BREAK",
            f"Trend broken: price Rs.{price:.1f} closed BELOW the 50-day "
            f"average (Rs.{float(sma50):.1f}). The healthy uptrend is over - "
            f"Minervini's rule says exit when this support fails.",
            score=0.9,
        )
    return None


def exit_kotegawa_meanrev(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Take profit at 25-SMA, stop at -5%, time stop at 15 days."""
    if len(df) < 25:
        return None
    close = df["Close"]
    price = float(close.iloc[-1])
    entry = float(trade["price"])
    sma25 = _sma(close, 25).iloc[-1]
    days = _days_held(trade)

    # Target: bounce to 25-SMA
    if not pd.isna(sma25) and price >= float(sma25):
        return _make_exit(
            trade, df, "TARGET",
            f"Bounce target hit: price Rs.{price:.1f} reached the 25-day "
            f"average (Rs.{float(sma25):.1f}). Mean reversion done - take profit.",
            score=0.7,
        )
    # Stop: -5% from entry
    if price <= entry * 0.95:
        return _make_exit(
            trade, df, "STOP",
            f"Stop hit: price Rs.{price:.1f} is 5%+ below your entry "
            f"Rs.{entry:.1f}. The dip kept dipping - cut losses.",
            score=1.0,
        )
    # Time: didn't bounce in 15 days
    if days > 15:
        return _make_exit(
            trade, df, "TIME",
            f"Time stop: held {days} days with no bounce to the 25-SMA. "
            f"Mean reversion that doesn't happen in ~3 weeks usually never does.",
            score=0.5,
        )
    return None


def exit_bnf_classic(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Tighter version of kotegawa: target 25-SMA, stop -3%, time 5 days."""
    if len(df) < 25:
        return None
    close = df["Close"]
    price = float(close.iloc[-1])
    entry = float(trade["price"])
    sma25 = _sma(close, 25).iloc[-1]
    days = _days_held(trade)

    if not pd.isna(sma25) and price >= float(sma25):
        return _make_exit(
            trade, df, "TARGET",
            f"BNF target hit: price Rs.{price:.1f} reached the 25-day average "
            f"(Rs.{float(sma25):.1f}) - the textbook BNF exit. Take profit.",
            score=0.7,
        )
    if price <= entry * 0.97:
        return _make_exit(
            trade, df, "STOP",
            f"BNF stop hit: price Rs.{price:.1f} is 3%+ below your entry "
            f"Rs.{entry:.1f}. BNF used tight stops - exit now.",
            score=1.0,
        )
    if days > 5:
        return _make_exit(
            trade, df, "TIME",
            f"BNF time stop: held {days} days. BNF's rule was 'bounce within "
            f"5 days or get out'. Reclaim the capital for the next setup.",
            score=0.5,
        )
    return None


def exit_darvas_box(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Stop -5% from entry; the breakout has failed."""
    close = df["Close"]
    price = float(close.iloc[-1])
    entry = float(trade["price"])
    if price <= entry * 0.95:
        return _make_exit(
            trade, df, "STOP",
            f"Darvas stop hit: price Rs.{price:.1f} fell 5%+ below your "
            f"breakout entry Rs.{entry:.1f}. The box-top breakout failed - "
            f"Darvas always cut losers fast.",
            score=1.0,
        )
    return None


def exit_turtle_breakout(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Classic Turtle System 1 exit: close < lowest low of last 10 days."""
    if len(df) < 11:
        return None
    close = df["Close"]
    low = df["Low"]
    price = float(close.iloc[-1])
    prior_low_10 = float(low.iloc[-11:-1].min())  # lowest low of last 10 days
    atr = _atr(df, 14).iloc[-1]
    entry = float(trade["price"])

    if price < prior_low_10:
        return _make_exit(
            trade, df, "TREND_BREAK",
            f"Turtle exit: price Rs.{price:.1f} closed below the 10-day low "
            f"(Rs.{prior_low_10:.1f}). This is the classic Turtle System 1 "
            f"exit rule - the trend has reversed.",
            score=0.9,
        )
    # 2N (2x ATR) hard stop from entry
    if not pd.isna(atr) and price <= entry - 2 * float(atr):
        return _make_exit(
            trade, df, "STOP",
            f"Turtle 2N stop hit: price Rs.{price:.1f} is more than 2x ATR "
            f"(Rs.{2 * float(atr):.1f}) below entry Rs.{entry:.1f}. "
            f"Turtle rule: never let a loser exceed 2N.",
            score=1.0,
        )
    return None


def exit_livermore_pivot(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Stop -5% (the pivot was supposed to become support; if not, exit)."""
    close = df["Close"]
    price = float(close.iloc[-1])
    entry = float(trade["price"])
    if price <= entry * 0.95:
        return _make_exit(
            trade, df, "STOP",
            f"Livermore stop hit: price Rs.{price:.1f} dropped 5%+ below "
            f"your pivot-breakout entry Rs.{entry:.1f}. The 'line of least "
            f"resistance' has reversed - Livermore would exit immediately.",
            score=1.0,
        )
    return None


def exit_zanger_breakout(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Stop -5% or held > 30 days (momentum should work fast)."""
    close = df["Close"]
    price = float(close.iloc[-1])
    entry = float(trade["price"])
    days = _days_held(trade)
    if price <= entry * 0.95:
        return _make_exit(
            trade, df, "STOP",
            f"Zanger stop hit: price Rs.{price:.1f} fell 5%+ below entry "
            f"Rs.{entry:.1f}. The momentum breakout failed - exit.",
            score=1.0,
        )
    if days > 30:
        return _make_exit(
            trade, df, "TIME",
            f"Zanger time exit: held {days} days. Momentum breakouts that "
            f"haven't paid off in a month rarely do. Free up the capital.",
            score=0.5,
        )
    return None


def exit_qullamaggie_ep(trade: dict, df: pd.DataFrame) -> Optional[ExitSignal]:
    """Stop -5% (gap fill) or take profit at +20%."""
    close = df["Close"]
    price = float(close.iloc[-1])
    entry = float(trade["price"])
    if price <= entry * 0.95:
        return _make_exit(
            trade, df, "STOP",
            f"Episodic Pivot stop hit: price Rs.{price:.1f} fell 5%+ below "
            f"the pivot day entry Rs.{entry:.1f}. The catalyst gap has "
            f"filled - the trade is invalidated.",
            score=1.0,
        )
    if price >= entry * 1.20:
        return _make_exit(
            trade, df, "TARGET",
            f"Episodic Pivot target hit: price Rs.{price:.1f} is up 20%+ "
            f"from entry Rs.{entry:.1f}. Qullamaggie typically scales out "
            f"at this level. Take partial or full profit.",
            score=0.7,
        )
    return None


# ---------- registry ----------

ALL_EXITS = {
    "minervini_lite":   exit_minervini_lite,
    "kotegawa_meanrev": exit_kotegawa_meanrev,
    "bnf_classic":      exit_bnf_classic,
    "darvas_box":       exit_darvas_box,
    "turtle_breakout":  exit_turtle_breakout,
    "livermore_pivot":  exit_livermore_pivot,
    "zanger_breakout":  exit_zanger_breakout,
    "qullamaggie_ep":   exit_qullamaggie_ep,
}


# ---------- top-level: check every open trade ----------

def check_exits_for_trades(
    trades: list[dict],
    fetch_history,
) -> list[dict]:
    """For each OPEN trade, run its strategy's exit rule and collect SELL signals.

    `fetch_history(ticker, period)` is injected so this module stays
    decoupled from yfinance/network concerns (easier to test).
    Returns a list of ExitSignal dicts (asdict-ed) sorted by urgency.
    """
    from dataclasses import asdict

    out: list[dict] = []
    for trade in trades:
        if trade.get("status") != "OPEN":
            continue
        strategy = trade.get("strategy")
        if not strategy or strategy not in ALL_EXITS:
            continue
        df = fetch_history(trade["ticker"], "1y")
        if df is None or df.empty:
            continue
        sig = ALL_EXITS[strategy](trade, df)
        if sig is not None:
            out.append(asdict(sig))
    out.sort(key=lambda s: s["score"], reverse=True)
    return out
