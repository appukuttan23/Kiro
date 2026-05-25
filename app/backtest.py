"""Real-data backtest engine.

Replays the 3 strategies day-by-day against historical OHLCV from yfinance,
applies the same exit rules used by Exit Watch, and reports per-strategy
performance with realistic friction (slippage + brokerage).

The engine deliberately mirrors `scripts/sandbox_validate.py` so that the
sandbox synthetic-data validation gives a 1:1 read on what this module does
on real data.

Pipeline:
  1. Pre-fetch full OHLCV for each ticker in the universe (one yfinance call
     per ticker, parallel via ThreadPoolExecutor) plus the benchmark.
  2. Walk forward t = warmup -> end_idx, day by day:
       a. Process exits on every open position using the strategy's exit rule.
       b. Run all 3 strategies on `df.iloc[:t+1]` for each ticker.
       c. Open new positions next bar (no look-ahead) subject to cooldown
          and "one-position-per-strategy-per-ticker" rule.
  3. Close any still-open trades at the final bar's price.
  4. Compute per-strategy and aggregate stats, daily equity curve, drawdown.

Known biases (documented for the dashboard):
  - Survivorship bias: yfinance shows only currently-listed tickers.
  - Look-ahead bias: mitigated by `df.iloc[:t+1]` slicing, but yfinance's
    auto-adjusted close incorporates future splits/dividends. Acceptable
    for swing-trade backtests, not for tick-precision research.
  - No participation rate / market-impact modeling.
  - Per-trade friction: slippage_pct + brokerage_pct subtracted from each
    round trip (default 0.3% total).

This module does not run in the Kiro sandbox (yfinance is unreachable).
Run locally:
    pip install -r requirements.txt
    curl 'http://localhost:8000/api/backtest?universe=NIFTY_50&years=5'
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from app.data import fetch_benchmark, fetch_history
from app.strategies import ALL_STRATEGIES, Signal
from app.universe import display_name, get_universe

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config + result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    universe: str = "NIFTY_50"
    years: int = 5                       # how many years of history to backtest
    starting_capital: float = 100_000.0  # virtual INR
    risk_per_trade_pct: float = 0.02     # 2% of capital risked per trade
    nominal_stop_pct: float = 0.05       # for sizing math (avg stop ~5%)
    slippage_pct: float = 0.001          # 10 bps each side
    brokerage_pct: float = 0.0005        # 5 bps each side
    cooldown_days: int = 10              # don't re-fire same strategy within N days

    @property
    def round_trip_friction(self) -> float:
        """Total cost as a fraction of trade value (entry + exit)."""
        return 2 * (self.slippage_pct + self.brokerage_pct)


@dataclass
class BacktestTrade:
    ticker: str
    strategy: str
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl_pct: float = 0.0          # post-friction
    pnl_pct_gross: float = 0.0    # pre-friction
    days_held: int = 0


@dataclass
class StrategyStats:
    name: str
    trades: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    expectancy_pct: float
    profit_factor: float
    avg_days_held: float


@dataclass
class BacktestResult:
    config: dict[str, Any]
    started_at: str
    finished_at: str
    duration_seconds: float
    universe_size: int
    tickers_with_data: int
    trades: list[dict[str, Any]]
    by_strategy: list[dict[str, Any]]
    overall_expectancy_pct: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    equity_curve: list[dict[str, Any]]   # [{date, equity}]
    notes: list[str]


# ---------------------------------------------------------------------------
# Exit rules (mirror Exit Watch / sandbox_validate.py)
# ---------------------------------------------------------------------------

def _should_exit(t: BacktestTrade, df: pd.DataFrame, today_idx: int) -> Optional[tuple[float, str]]:
    """Returns (exit_price, reason) if today triggers an exit, else None.

    Uses today's close as the exit price (conservative — assumes you exit
    at close, not on the next day's gap-up/down). Caller adds friction.
    """
    today_price = float(df["Close"].iloc[today_idx])
    entry_idx = df.index.get_loc(pd.to_datetime(t.entry_date))
    days = today_idx - entry_idx

    if t.strategy == "minervini_lite":
        if today_price <= t.entry_price * 0.93:
            return (today_price, "stop -7%")
        # 50-day MA trail (only after 3 days held to avoid noise around entry)
        if today_idx >= 50 and days >= 3:
            s50 = float(df["Close"].iloc[today_idx - 49: today_idx + 1].mean())
            if today_price < s50:
                return (today_price, "below 50-MA")
        if today_price >= t.entry_price * 1.20:
            return (today_price, "+20% target")

    elif t.strategy == "kotegawa_meanrev":
        if today_price <= t.entry_price * 0.97:
            return (today_price, "stop -3%")
        if today_price >= t.entry_price * 1.05:
            return (today_price, "+5% target")
        if days >= 10:
            return (today_price, "time-stop 10d")

    elif t.strategy == "darvas_breakout":
        if today_price <= t.entry_price * 0.95:
            return (today_price, "stop -5%")
        if today_price >= t.entry_price * 1.10 and days >= 3:
            return (today_price, "+10% target")
        if days >= 30:
            return (today_price, "time-stop 30d")

    return None


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _strategy_stats(name: str, trades: list[BacktestTrade]) -> StrategyStats:
    if not trades:
        return StrategyStats(name=name, trades=0, win_rate_pct=0.0,
                             avg_win_pct=0.0, avg_loss_pct=0.0,
                             expectancy_pct=0.0, profit_factor=0.0,
                             avg_days_held=0.0)
    wins = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    losses = [t.pnl_pct for t in trades if t.pnl_pct <= 0]
    wr = len(wins) / len(trades) * 100
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    exp = sum(t.pnl_pct for t in trades) / len(trades)
    gw = sum(wins) if wins else 0.0
    gl = abs(sum(losses)) if losses else 0.0001
    pf = gw / gl
    ah = sum(t.days_held for t in trades) / len(trades)
    return StrategyStats(name=name, trades=len(trades),
                         win_rate_pct=round(wr, 2),
                         avg_win_pct=round(aw, 2),
                         avg_loss_pct=round(al, 2),
                         expectancy_pct=round(exp, 2),
                         profit_factor=round(pf, 2),
                         avg_days_held=round(ah, 1))


def _equity_curve(trades: list[BacktestTrade], cfg: BacktestConfig
                  ) -> tuple[list[dict[str, Any]], float, float, float]:
    """Compute equity curve from chronologically-sorted trade exits.

    Sizing model: each trade is sized so that a full -nominal_stop_pct stop
    would equal -risk_per_trade_pct of current capital. Returns:
      curve, final_equity, total_return_pct, max_drawdown_pct
    """
    if not trades:
        return [], cfg.starting_capital, 0.0, 0.0

    risk_to_stop_ratio = cfg.risk_per_trade_pct / cfg.nominal_stop_pct
    capital = cfg.starting_capital
    peak = capital
    max_dd = 0.0
    curve = [{"date": "start", "equity": round(capital, 2)}]
    sequenced = sorted(trades, key=lambda t: t.exit_date)
    for t in sequenced:
        capital *= (1 + (t.pnl_pct / 100) * risk_to_stop_ratio)
        peak = max(peak, capital)
        dd = (peak - capital) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
        curve.append({"date": t.exit_date, "equity": round(capital, 2)})

    total_return_pct = (capital / cfg.starting_capital - 1) * 100
    return curve, round(capital, 2), round(total_return_pct, 2), round(max_dd, 2)


# ---------------------------------------------------------------------------
# Pre-fetch
# ---------------------------------------------------------------------------

def _fetch_one(ticker: str, period: str) -> tuple[str, Optional[pd.DataFrame]]:
    df = fetch_history(ticker, period=period)
    return ticker, df


def _fetch_universe(tickers: list[str], years: int) -> dict[str, pd.DataFrame]:
    """Parallel-fetch all tickers. Returns only tickers that returned data."""
    period = f"{max(years + 1, 2)}y"  # +1y for warmup
    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for ticker, df in pool.map(lambda t: _fetch_one(t, period), tickers):
            if df is not None and len(df) >= 252:
                out[ticker] = df
    return out


# ---------------------------------------------------------------------------
# Per-ticker simulation
# ---------------------------------------------------------------------------

def _simulate_ticker(ticker: str, df: pd.DataFrame,
                     benchmark: Optional[pd.DataFrame],
                     cfg: BacktestConfig, warmup: int,
                     cutoff_date) -> list[BacktestTrade]:
    """Walk forward through one ticker's history. Returns closed trades."""
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if len(df) < warmup + 30:
        return []

    df_dates = df.index.date
    # First bar at or after cutoff (or the warmup point, whichever is later)
    after_cutoff_mask = df_dates >= cutoff_date
    if not after_cutoff_mask.any():
        return []
    start_idx = max(warmup, int(after_cutoff_mask.argmax()))

    trades: list[BacktestTrade] = []
    open_positions: list[BacktestTrade] = []
    last_entry_idx_by_strategy: dict[str, int] = {}

    for t in range(start_idx, len(df) - 1):
        # 1. Process exits
        still_open: list[BacktestTrade] = []
        for trade in open_positions:
            res = _should_exit(trade, df, t)
            if res is not None:
                raw_exit_price, reason = res
                gross_pnl = (raw_exit_price / trade.entry_price - 1) * 100
                net_pnl = gross_pnl - cfg.round_trip_friction * 100
                trade.exit_date = df.index[t].date().isoformat()
                trade.exit_price = round(raw_exit_price, 4)
                trade.exit_reason = reason
                trade.pnl_pct_gross = round(gross_pnl, 4)
                trade.pnl_pct = round(net_pnl, 4)
                entry_idx = df.index.get_loc(pd.to_datetime(trade.entry_date))
                trade.days_held = t - entry_idx
                trades.append(trade)
            else:
                still_open.append(trade)
        open_positions = still_open

        # 2. Look for new signals (data available up to and including today)
        df_so_far = df.iloc[: t + 1]
        bench_so_far: Optional[pd.DataFrame] = None
        if benchmark is not None:
            bench_so_far = benchmark[benchmark.index <= df.index[t]]

        for name, fn in ALL_STRATEGIES.items():
            if (name in last_entry_idx_by_strategy
                    and (t - last_entry_idx_by_strategy[name]) < cfg.cooldown_days):
                continue
            if any(p.strategy == name for p in open_positions):
                continue

            sig: Optional[Signal] = fn(ticker, df_so_far,
                                       benchmark_df=bench_so_far,
                                       earnings_days_away=None)
            if sig is None:
                continue

            # Enter on next bar's open (no look-ahead)
            next_bar = df.iloc[t + 1]
            entry_price = float(next_bar.get("Open", next_bar["Close"]))
            next_date_str = df.index[t + 1].date().isoformat()
            open_positions.append(BacktestTrade(
                ticker=ticker,
                strategy=name,
                entry_date=next_date_str,
                entry_price=round(entry_price, 4),
            ))
            last_entry_idx_by_strategy[name] = t + 1

    # Close any still-open positions at the last bar's close
    if open_positions:
        last_t = len(df) - 1
        last_price = float(df["Close"].iloc[last_t])
        last_date = df.index[last_t].date().isoformat()
        for trade in open_positions:
            gross_pnl = (last_price / trade.entry_price - 1) * 100
            net_pnl = gross_pnl - cfg.round_trip_friction * 100
            trade.exit_date = last_date
            trade.exit_price = round(last_price, 4)
            trade.exit_reason = "end-of-backtest"
            trade.pnl_pct_gross = round(gross_pnl, 4)
            trade.pnl_pct = round(net_pnl, 4)
            entry_idx = df.index.get_loc(pd.to_datetime(trade.entry_date))
            trade.days_held = last_t - entry_idx
            trades.append(trade)

    return trades


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_backtest(cfg: BacktestConfig) -> BacktestResult:
    """Run a backtest with the given config. May take 30s - 3 min on real data.

    The dashboard calls this in a worker thread.
    """
    started_at = datetime.utcnow()
    log.info("Backtest start: universe=%s years=%s", cfg.universe, cfg.years)

    tickers = get_universe(cfg.universe)
    history = _fetch_universe(tickers, years=cfg.years)
    benchmark = fetch_benchmark(period=f"{max(cfg.years + 1, 2)}y")
    if benchmark is None:
        log.warning("Benchmark fetch failed; relative-strength filter disabled")
    elif not isinstance(benchmark.index, pd.DatetimeIndex):
        benchmark = benchmark.copy()
        benchmark.index = pd.to_datetime(benchmark.index)

    warmup = 220
    cutoff = datetime.utcnow().date() - timedelta(days=int(cfg.years * 365.25))

    all_trades: list[BacktestTrade] = []
    for ticker, df in history.items():
        all_trades.extend(_simulate_ticker(ticker, df, benchmark, cfg, warmup, cutoff))

    # Aggregate stats
    by_strategy = [
        asdict(_strategy_stats(name, [t for t in all_trades if t.strategy == name]))
        for name in ALL_STRATEGIES
    ]
    total_pnl = sum(t.pnl_pct for t in all_trades)
    overall_exp = round(total_pnl / len(all_trades), 3) if all_trades else 0.0
    curve, final_eq, ret_pct, max_dd = _equity_curve(all_trades, cfg)

    finished_at = datetime.utcnow()
    notes = [
        f"Friction applied: {cfg.round_trip_friction * 100:.2f}% round-trip per trade.",
        "Survivorship bias: yfinance shows only currently-listed tickers.",
        "Slippage assumed: 10 bps each side. Brokerage: 5 bps each side.",
        f"Position sizing: {cfg.risk_per_trade_pct * 100:.0f}% account risk per "
        f"trade with {cfg.nominal_stop_pct * 100:.0f}% nominal stop.",
        "Synthetic backtests typically over-state expectancy 2-3x; "
        "this real-data run is the better benchmark.",
    ]

    return BacktestResult(
        config=asdict(cfg),
        started_at=started_at.isoformat(timespec="seconds") + "Z",
        finished_at=finished_at.isoformat(timespec="seconds") + "Z",
        duration_seconds=round((finished_at - started_at).total_seconds(), 1),
        universe_size=len(tickers),
        tickers_with_data=len(history),
        trades=[asdict(t) for t in all_trades],
        by_strategy=by_strategy,
        overall_expectancy_pct=overall_exp,
        final_equity=final_eq,
        total_return_pct=ret_pct,
        max_drawdown_pct=max_dd,
        equity_curve=curve,
        notes=notes,
    )
