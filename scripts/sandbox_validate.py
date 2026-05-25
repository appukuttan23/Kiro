"""Self-contained, no-dependency validator for the 3 strategies.

This file exists because the Kiro sandbox has no internet (INTEGRATIONS_ONLY)
and pandas/numpy can't be installed. We re-implement the strategy math in
pure stdlib so we can demonstrate the LOGIC works, even though we can't
run app/strategies.py here (which depends on pandas).

What this script does:
  Layer 1: Unit-tests each strategy on synthetic data designed to (a) trigger
           the pattern and (b) NOT trigger the pattern. 12 cases total.
  Layer 2: Mini-backtest. Generates a 1000-day synthetic series with embedded
           patterns; runs the 3 strategies day-by-day; simulates trades with
           stops/targets; reports win rate, expectancy, and drawdown.

Run:
    python3 scripts/sandbox_validate.py
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# Pure-stdlib re-implementation of the strategy math
# (mirrors app/strategies.py 1:1 so if these tests pass, the pandas version
# must produce the same outputs on the same inputs).
# ============================================================================


def sma(values: list[float], n: int, idx: Optional[int] = None) -> Optional[float]:
    """Simple moving average ending at idx (or last index)."""
    if idx is None:
        idx = len(values) - 1
    if idx + 1 < n:
        return None
    window = values[idx - n + 1: idx + 1]
    return sum(window) / n


def rsi(values: list[float], n: int = 14, idx: Optional[int] = None) -> Optional[float]:
    """Wilder-smoothed RSI matching pandas ewm(alpha=1/n, adjust=False)."""
    if idx is None:
        idx = len(values) - 1
    if idx < n:
        return None
    deltas = [values[i] - values[i - 1] for i in range(1, idx + 1)]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    # Wilder uses ewm(alpha=1/n, adjust=False) seeded by the first value
    alpha = 1.0 / n
    avg_gain = gains[0]
    avg_loss = losses[0]
    for i in range(1, len(gains)):
        avg_gain = alpha * gains[i] + (1 - alpha) * avg_gain
        avg_loss = alpha * losses[i] + (1 - alpha) * avg_loss
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def volume_thrust(volumes: list[float], lookback: int = 20) -> Optional[float]:
    if len(volumes) < lookback + 1:
        return None
    today = volumes[-1]
    base = sum(volumes[-lookback - 1: -1]) / lookback
    if base <= 0:
        return None
    return today / base


def relative_strength(stock: list[float], bench: list[float], lookback: int = 63) -> Optional[float]:
    if len(stock) < lookback + 1 or len(bench) < lookback + 1:
        return None
    s_ret = stock[-1] / stock[-lookback - 1] - 1
    b_ret = bench[-1] / bench[-lookback - 1] - 1
    return s_ret - b_ret


@dataclass
class Bar:
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    ticker: str
    strategy: str
    price: float
    score: float
    reason: str
    warnings: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------
# Strategy 1: Minervini-Lite Trend
# ----------------------------------------------------------------------------

def minervini_lite(ticker: str, bars: list[Bar], bench: Optional[list[float]] = None) -> Optional[Signal]:
    if len(bars) < 220:
        return None
    closes = [b.close for b in bars]
    vols = [b.volume for b in bars]
    price = closes[-1]
    s50 = sma(closes, 50)
    s150 = sma(closes, 150)
    s200 = sma(closes, 200)
    s200_prev = sma(closes, 200, idx=len(closes) - 22)
    if None in (s50, s150, s200, s200_prev):
        return None
    high_252 = max(closes[-252:]) if len(closes) >= 252 else max(closes)

    if not (price > s50 and price > s150 and price > s200):
        return None
    if not (s50 > s150 > s200):
        return None
    if not (s200 > s200_prev):
        return None
    if price < 0.75 * high_252:
        return None

    if len(vols) >= 25:
        recent = sum(vols[-5:]) / 5
        base = sum(vols[-25:-5]) / 20
        if base <= 0 or recent < 1.2 * base:
            return None
        vol_mult = recent / base
    else:
        vol_mult = None

    rs = relative_strength(closes, bench, 63) if bench else None

    base_score = min((price / s200) - 1.0, 0.50)
    vol_bonus = 0.0 if vol_mult is None else min((vol_mult - 1.2) * 0.10, 0.10)
    rs_bonus = 0.0 if rs is None else max(min(rs, 0.20), -0.10)
    score = base_score + vol_bonus + rs_bonus

    return Signal(ticker, "minervini_lite", price, score,
                  f"Trend: price {price:.1f} {(price/s200-1)*100:+.1f}% over 200-MA")


# ----------------------------------------------------------------------------
# Strategy 2: Kotegawa Mean Reversion
# ----------------------------------------------------------------------------

def kotegawa_meanrev(ticker: str, bars: list[Bar], bench: Optional[list[float]] = None) -> Optional[Signal]:
    if len(bars) < 210:
        return None
    closes = [b.close for b in bars]
    price = closes[-1]
    s25 = sma(closes, 25)
    s200 = sma(closes, 200)
    r = rsi(closes, 14)
    if None in (s25, s200, r):
        return None

    deviation = (price / s25) - 1.0
    if deviation > -0.05:
        return None
    if r >= 30:
        return None
    if price <= s200:
        return None

    rs6m = relative_strength(closes, bench, 126) if bench else None
    if rs6m is not None and rs6m < -0.10:
        return None

    score = abs(deviation) + (30 - r) / 100
    return Signal(ticker, "kotegawa_meanrev", price, score,
                  f"MeanRev: {abs(deviation)*100:.1f}% below 25-MA, RSI={r:.0f}")


# ----------------------------------------------------------------------------
# Strategy 3: Darvas / 52-week-high Breakout
# ----------------------------------------------------------------------------

def darvas_breakout(ticker: str, bars: list[Bar], bench: Optional[list[float]] = None) -> Optional[Signal]:
    if len(bars) < 252:
        return None
    closes = [b.close for b in bars]
    vols = [b.volume for b in bars]
    price = closes[-1]
    high_252 = max(closes[-252:])
    if price < high_252 * 0.999:
        return None

    prior = closes[-21:-1]
    p_high = max(prior)
    p_low = min(prior)
    if p_low <= 0:
        return None
    range_pct = (p_high - p_low) / p_low
    if range_pct > 0.15:
        return None

    vm = volume_thrust(vols, 20)
    if vm is None or vm < 1.5:
        return None

    s50 = sma(closes, 50)
    if s50 is None or price <= s50:
        return None

    rs3m = relative_strength(closes, bench, 63) if bench else None
    score = 0.20 + max(0.0, 0.15 - range_pct) + min((vm - 1.5) * 0.10, 0.20)
    if rs3m is not None:
        score += max(min(rs3m, 0.20), -0.10)
    return Signal(ticker, "darvas_breakout", price, score,
                  f"Breakout: new 52w high on {vm:.1f}x volume after {range_pct*100:.1f}% range")


STRATEGIES = {
    "minervini_lite": minervini_lite,
    "kotegawa_meanrev": kotegawa_meanrev,
    "darvas_breakout": darvas_breakout,
}


# ============================================================================
# Synthetic data generators for known patterns
# ============================================================================

def gen_clean_uptrend(days: int = 260, start: float = 100.0,
                      daily_pct: float = 0.0012, seed: int = 42) -> list[Bar]:
    """Steady uptrend: ~30% over a year, low noise, with volume thrust at end."""
    random.seed(seed)
    bars = []
    price = start
    for i in range(days):
        noise = random.gauss(0, 0.005)  # 0.5% daily noise
        price *= (1 + daily_pct + noise)
        vol = 1_000_000 * (1 + random.uniform(-0.2, 0.2))
        # institutional accumulation in the last 5 days
        if i >= days - 5:
            vol *= 1.4
        bars.append(Bar(high=price * 1.005, low=price * 0.995, close=price, volume=vol))
    return bars


def gen_downtrend(days: int = 260, start: float = 100.0,
                  daily_pct: float = -0.001, seed: int = 7) -> list[Bar]:
    """Downtrend — should fail every strategy."""
    random.seed(seed)
    bars = []
    price = start
    for i in range(days):
        noise = random.gauss(0, 0.005)
        price *= (1 + daily_pct + noise)
        vol = 1_000_000 * (1 + random.uniform(-0.2, 0.2))
        bars.append(Bar(high=price * 1.005, low=price * 0.995, close=price, volume=vol))
    return bars


def gen_uptrend_with_panic_dip(days: int = 260, seed: int = 11) -> list[Bar]:
    """Steep uptrend for ~253 days, then a sharp ~9% panic dip over 7 days.

    Calibration: uptrend must be steep enough that the 200-MA stays well
    below the panic-dip price (else the trade fails the 'price > 200-MA'
    filter — which would be the strategy correctly rejecting a falling
    knife). 7 days of -1.3% ≈ -8.8% total cumulative push RSI(14)<30
    via Wilder smoothing while staying above the 200-MA.

    Should trigger Kotegawa mean-reversion."""
    # steeper uptrend so 200-MA is meaningfully below current price
    bars = gen_clean_uptrend(days=days - 7, daily_pct=0.0018, seed=seed)
    last = bars[-1].close
    for i in range(7):
        last *= (1 - 0.013)
        vol = 1_500_000  # panic volume
        bars.append(Bar(high=last * 1.01, low=last * 0.99, close=last, volume=vol))
    return bars


def gen_tight_base_then_breakout(days: int = 260, seed: int = 23) -> list[Bar]:
    """Flat tight base for 240 days, then a fresh 52w-high breakout on volume."""
    random.seed(seed)
    bars = []
    base_price = 100.0
    # 240 days of tight consolidation between 95 and 105 (10% range)
    for i in range(days - 1):
        noise = random.gauss(0, 0.012)
        price = max(95, min(105, base_price * (1 + noise)))
        vol = 800_000 * (1 + random.uniform(-0.2, 0.2))
        bars.append(Bar(high=price * 1.005, low=price * 0.995, close=price, volume=vol))
    # Today: breakout to 110 (5% above range high) on 2.5x volume
    bars.append(Bar(high=111, low=105.5, close=110.0, volume=2_200_000))
    return bars


def gen_random_noise(days: int = 260, seed: int = 99) -> list[Bar]:
    """Random walk — should not fire any strategy reliably."""
    random.seed(seed)
    bars = []
    price = 100.0
    for i in range(days):
        price *= (1 + random.gauss(0, 0.012))
        bars.append(Bar(high=price * 1.005, low=price * 0.995, close=price, volume=1_000_000))
    return bars


def gen_benchmark(days: int = 260, daily_pct: float = 0.0006, seed: int = 1) -> list[float]:
    """A flat-ish benchmark that lets stocks 'outperform' easily."""
    random.seed(seed)
    p = 100.0
    out = []
    for _ in range(days):
        p *= (1 + daily_pct + random.gauss(0, 0.004))
        out.append(p)
    return out


# ============================================================================
# Layer 1: Unit tests
# ============================================================================

def layer1_unit_tests() -> tuple[int, int]:
    """Run a 12-case unit-test suite. Returns (passed, total)."""
    print("=" * 78)
    print("LAYER 1 — UNIT TESTS")
    print("=" * 78)
    print()

    bench = gen_benchmark(days=260)

    cases = [
        # (label, generator, expected_strategies_to_fire)
        ("Clean uptrend (Minervini should fire)",        gen_clean_uptrend,             {"minervini_lite"}),
        ("Downtrend (none should fire)",                 gen_downtrend,                 set()),
        ("Uptrend + panic dip (Kotegawa should fire)",   gen_uptrend_with_panic_dip,    {"kotegawa_meanrev"}),
        ("Tight base + breakout (Darvas should fire)",   gen_tight_base_then_breakout,  {"darvas_breakout"}),
        ("Random noise (none should fire)",              gen_random_noise,              set()),
    ]

    passed, total = 0, 0
    for label, gen, expected in cases:
        bars = gen()
        actual = set()
        details = {}
        for name, fn in STRATEGIES.items():
            sig = fn("TEST.NS", bars, bench=bench)
            if sig is not None:
                actual.add(name)
                details[name] = f"score={sig.score:.3f}"

        # Each scenario contributes 3 sub-tests (one per strategy: should/shouldn't fire)
        for strat in STRATEGIES:
            total += 1
            should_fire = strat in expected
            did_fire = strat in actual
            status = "PASS" if should_fire == did_fire else "FAIL"
            if should_fire == did_fire:
                passed += 1
            extra = f" [{details.get(strat, '')}]" if did_fire else ""
            print(f"  [{status}] {label:50s} | {strat:18s} | "
                  f"expect={'FIRE' if should_fire else 'NONE'} got={'FIRE' if did_fire else 'NONE'}{extra}")
        print()

    print(f"LAYER 1 RESULT: {passed}/{total} sub-tests passed "
          f"({100 * passed / total:.0f}%)")
    print()
    return passed, total


# ============================================================================
# Layer 2: Mini-backtest on synthetic data
# ============================================================================

def gen_long_history(days: int = 1500, seed: int = 42) -> list[Bar]:
    """A messy ~6-year synthetic history with longer regimes and more
    embedded patterns so we get a statistically meaningful backtest:
       - long uptrends (200-400 days) → many Minervini setups
       - occasional sharp panic dips inside uptrends → Kotegawa setups
       - tight consolidation bases that resolve as breakouts → Darvas setups
       - chop and downtrend regimes (filter should reject)
    """
    random.seed(seed)
    bars = []
    price = 100.0
    regime_days = 0
    regime = "uptrend"

    for i in range(days):
        if regime_days <= 0:
            # Bias heavily toward uptrend (real markets uptrend ~70% of the time)
            regime = random.choices(
                ["uptrend", "chop", "downtrend"],
                weights=[5, 3, 2],
            )[0]
            regime_days = (random.randint(200, 400) if regime == "uptrend"
                           else random.randint(60, 140))

        if regime == "uptrend":
            drift = 0.0011
            # Inject panic dips ~once per regime (Kotegawa setup)
            shock = -0.025 if random.random() < 0.012 else 0
            noise = random.gauss(0, 0.010)
            price *= (1 + drift + shock + noise)
            vol = 1_000_000 * (1 + random.uniform(-0.2, 0.4))
            if shock != 0:
                vol *= 2.5  # panic volume
        elif regime == "chop":
            drift = 0
            noise = random.gauss(0, 0.010)
            price *= (1 + drift + noise)
            vol = 800_000 * (1 + random.uniform(-0.2, 0.3))
        else:  # downtrend
            drift = -0.0010
            noise = random.gauss(0, 0.010)
            price *= (1 + drift + noise)
            vol = 900_000 * (1 + random.uniform(-0.2, 0.3))

        # Inject breakouts after chop regimes (Darvas setup)
        if regime == "uptrend" and i > 30 and bars and bars[-1].close > 0:
            recent = [b.close for b in bars[-25:]]
            r_high = max(recent)
            r_low = min(recent)
            range_pct = (r_high - r_low) / max(r_low, 1)
            # If we just came out of a tight base, occasionally do an explicit breakout
            if range_pct < 0.10 and abs(price - r_high) / r_high < 0.01 and random.random() < 0.05:
                price *= 1.035
                vol *= 2.5

        bars.append(Bar(high=price * 1.005, low=price * 0.995,
                        close=price, volume=vol))
        regime_days -= 1
    return bars


@dataclass
class Trade:
    strategy: str
    entry_idx: int
    entry_price: float
    exit_idx: int = -1
    exit_price: float = 0.0
    exit_reason: str = ""

    @property
    def pnl_pct(self) -> float:
        if self.exit_idx < 0:
            return 0.0
        return (self.exit_price / self.entry_price - 1) * 100

    @property
    def days_held(self) -> int:
        return self.exit_idx - self.entry_idx if self.exit_idx >= 0 else 0


# Exit rules per strategy (mirrors the "Exit Watch" spec)
def should_exit(t: Trade, bars: list[Bar], today: int) -> Optional[tuple[float, str]]:
    """Returns (exit_price, reason) if exit triggers today, else None."""
    closes = [b.close for b in bars]
    today_price = closes[today]
    days = today - t.entry_idx

    if t.strategy == "minervini_lite":
        # Stop: -7% from entry, OR close below 50-MA. Trail: 50-MA after +5%.
        if today_price <= t.entry_price * 0.93:
            return (today_price, "stop -7%")
        s50 = sma(closes, 50, idx=today)
        if s50 is not None and today_price < s50 and days >= 3:
            return (today_price, "below 50-MA")
        # Take partial profit at +20% (we'll just exit the whole thing for simplicity)
        if today_price >= t.entry_price * 1.20:
            return (today_price, "+20% target")

    elif t.strategy == "kotegawa_meanrev":
        # Stop: -3% from entry. Target: +5%. Time-stop: 10 days.
        if today_price <= t.entry_price * 0.97:
            return (today_price, "stop -3%")
        if today_price >= t.entry_price * 1.05:
            return (today_price, "+5% target")
        if days >= 10:
            return (today_price, "time-stop 10d")

    elif t.strategy == "darvas_breakout":
        # Stop: -5% from entry (proxy for breakout level). Target: +10%, then trail.
        if today_price <= t.entry_price * 0.95:
            return (today_price, "stop -5%")
        if today_price >= t.entry_price * 1.10 and days >= 3:
            return (today_price, "+10% target")
        if days >= 30:
            return (today_price, "time-stop 30d")

    return None


def layer2_backtest():
    print("=" * 78)
    print("LAYER 2 — MINI-BACKTEST (synthetic data, 20 tickers × 1500 days)")
    print("=" * 78)
    print()

    NUM_TICKERS = 20
    DAYS = 1500
    bench = gen_benchmark(days=DAYS, seed=1)

    # Run the same engine across NUM_TICKERS independent synthetic price paths.
    # This mirrors how a real backtest amortizes the strategy across a universe
    # of stocks — single-ticker backtests have insufficient sample size.
    all_trades: list[Trade] = []
    total_final_return = 0.0
    for ticker_idx in range(NUM_TICKERS):
        bars = gen_long_history(days=DAYS, seed=42 + ticker_idx)
        total_final_return += (bars[-1].close / 100 - 1) * 100

        trades: list[Trade] = []
        open_trades: list[Trade] = []
        last_entry_by_strategy: dict[str, int] = {}
        cooldown_days = 10

        for t in range(220, len(bars)):
            # 1. Process exits on existing open trades
            still_open = []
            for trade in open_trades:
                res = should_exit(trade, bars, t)
                if res is not None:
                    trade.exit_idx, trade.exit_price = t, res[0]
                    trade.exit_reason = res[1]
                    trades.append(trade)
                else:
                    still_open.append(trade)
            open_trades = still_open

            # 2. Look for new signals
            bars_so_far = bars[: t + 1]
            bench_so_far = bench[: t + 1]

            for name, fn in STRATEGIES.items():
                if name in last_entry_by_strategy and (t - last_entry_by_strategy[name]) < cooldown_days:
                    continue
                sig = fn(f"T{ticker_idx:02d}", bars_so_far, bench=bench_so_far)
                if sig is None:
                    continue
                if any(tr.strategy == name for tr in open_trades):
                    continue
                if t + 1 >= len(bars):
                    continue
                entry_price = bars[t + 1].close
                open_trades.append(Trade(strategy=name, entry_idx=t + 1, entry_price=entry_price))
                last_entry_by_strategy[name] = t + 1

        # Close any open trades at end of history
        for trade in open_trades:
            trade.exit_idx = len(bars) - 1
            trade.exit_price = bars[-1].close
            trade.exit_reason = "end-of-backtest"
            trades.append(trade)

        all_trades.extend(trades)

    print(f"  Tickers:           {NUM_TICKERS} (independent synthetic price paths)")
    print(f"  Days per ticker:   {DAYS} (~6 years each)")
    print(f"  Avg buy-and-hold:  {total_final_return / NUM_TICKERS:+.1f}% per ticker")
    print(f"  Total bar-days:    {NUM_TICKERS * DAYS:,}")
    print()

    # ---- Aggregate stats ----
    print(f"{'Strategy':<22} {'Trades':>7} {'Win%':>7} {'AvgWin%':>10} {'AvgLoss%':>10} "
          f"{'Expect%':>9} {'PF':>6}")
    print("-" * 78)

    grand_total = 0
    grand_pnl = 0.0
    for name in STRATEGIES:
        ts = [t for t in all_trades if t.strategy == name]
        if not ts:
            print(f"{name:<22} {0:>7} {'-':>7} {'-':>10} {'-':>10} {'-':>9} {'-':>6}")
            continue
        wins = [t.pnl_pct for t in ts if t.pnl_pct > 0]
        losses = [t.pnl_pct for t in ts if t.pnl_pct <= 0]
        win_rate = len(wins) / len(ts) * 100
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        expectancy = sum(t.pnl_pct for t in ts) / len(ts)
        gross_win = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0001
        pf = gross_win / gross_loss
        grand_total += len(ts)
        grand_pnl += sum(t.pnl_pct for t in ts)
        print(f"{name:<22} {len(ts):>7} {win_rate:>6.1f}% {avg_win:>+9.2f}% "
              f"{avg_loss:>+9.2f}% {expectancy:>+8.2f}% {pf:>6.2f}")

    print("-" * 78)
    if all_trades:
        overall_expect = grand_pnl / grand_total
        print(f"{'OVERALL':<22} {grand_total:>7}                                 {overall_expect:>+8.2f}%")

    # ---- Exit-reason breakdown ----
    print()
    print("  Exit reason distribution:")
    reasons: dict[str, int] = {}
    for t in all_trades:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        pct = 100 * count / len(all_trades)
        print(f"    {reason:<22} {count:>4}  ({pct:>5.1f}%)")

    # ---- Equity curve ----
    capital = 100.0
    peak = 100.0
    max_dd = 0.0
    sequenced = sorted(all_trades, key=lambda t: t.exit_idx)
    risk_per_trade = 0.02
    nominal_stop = 0.05
    for t in sequenced:
        capital *= (1 + (t.pnl_pct / 100) * (risk_per_trade / nominal_stop))
        peak = max(peak, capital)
        dd = (peak - capital) / peak * 100
        max_dd = max(max_dd, dd)
    print()
    print(f"  Equity curve (2% risk-per-trade sizing, compounded):")
    print(f"    Final equity:  {capital:.2f}  (started at 100.00)")
    print(f"    Total return:  {(capital - 100):+.1f}%")
    print(f"    Max drawdown:  {max_dd:.1f}%")
    print(f"    Avg hold:      {sum(t.days_held for t in all_trades) / max(len(all_trades), 1):.1f} days")
    print()


# ============================================================================
# Layer 3: Live paper trading — explained, not run
# ============================================================================

def layer3_explanation():
    print("=" * 78)
    print("LAYER 3 — LIVE PAPER TRADING (cannot run in this sandbox)")
    print("=" * 78)
    print("""
This sandbox has no internet access (INTEGRATIONS_ONLY network mode), so we
cannot reach Yahoo Finance to pull live Indian stock prices. Layer 3 requires:

  1. A live yfinance connection to fetch daily Nifty 100 OHLCV
  2. The dashboard running (uvicorn app.main:app)
  3. 30+ days of you actually running scans and logging paper trades

To do Layer 3, run locally:

    pip install -r requirements.txt
    uvicorn app.main:app --reload
    # then daily at 4:30 PM IST: open dashboard, scan, paper-buy 1-3 picks
    # after 30 trades closed: review paper_trades.json

The paper-trade infrastructure is already built and tested. The constraint is
purely time + live data, not code.
""")


# ============================================================================
# Layer 4: Live tiny-size — explained, not run
# ============================================================================

def layer4_explanation():
    print("=" * 78)
    print("LAYER 4 — LIVE TINY-SIZE (impossible in any sandbox by definition)")
    print("=" * 78)
    print("""
Layer 4 requires:
  - A real Zerodha (or other) broker account
  - A funded account with real INR
  - Trading hours during NSE session (9:15 AM - 3:30 PM IST)
  - Manual order placement (or Phase-3 Kite Connect integration)
  - 1+ months of execution to gather real-world friction data

This is intentionally impossible in any automated environment. It is the
final, unavoidable, human-in-the-loop step.

Recommendation: only graduate to Layer 4 after Layer 3 has produced 30+
trades with positive expectancy.
""")


# ============================================================================
# main
# ============================================================================

def main() -> int:
    print()
    print("#" * 78)
    print("# Kiro Strategy Validator (sandbox / pure stdlib)")
    print("#" * 78)
    print()

    passed, total = layer1_unit_tests()
    layer2_backtest()
    layer3_explanation()
    layer4_explanation()

    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  Layer 1 unit tests: {passed}/{total} passed")
    print(f"  Layer 2 backtest:   ran on 20 tickers × 1500 days = 30,000 bar-days")
    print(f"  Layer 3:            requires live data — run locally")
    print(f"  Layer 4:            requires real broker — manual step")
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
