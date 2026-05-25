"""Production unit tests for app/strategies.py.

Run locally with:
    pip install -r requirements.txt
    pytest tests/

These tests can NOT run in the Kiro sandbox because pandas/numpy/yfinance
are not installable there (INTEGRATIONS_ONLY network mode). For sandbox
demo run `python3 scripts/sandbox_validate.py` which re-implements the
math in pure stdlib and verifies the same logic.

Tests are deterministic — they use a fixed RNG seed.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from app.strategies import (
    Signal,
    darvas_breakout,
    kotegawa_meanrev,
    minervini_lite,
)


# ---------------------------------------------------------------------------
# Synthetic data generators
# ---------------------------------------------------------------------------

def _make_bars(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000] * n
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open": closes,
        "High": [c * 1.005 for c in closes],
        "Low": [c * 0.995 for c in closes],
        "Close": closes,
        "Volume": volumes,
    }, index=dates)


def _gen_uptrend(days: int = 260, daily_pct: float = 0.0012, seed: int = 42) -> pd.DataFrame:
    random.seed(seed)
    price = 100.0
    closes, vols = [], []
    for i in range(days):
        price *= (1 + daily_pct + random.gauss(0, 0.005))
        closes.append(price)
        vol = 1_000_000 * (1 + random.uniform(-0.2, 0.2))
        if i >= days - 5:
            vol *= 1.4  # institutional accumulation
        vols.append(vol)
    return _make_bars(closes, vols)


def _gen_downtrend(days: int = 260, seed: int = 7) -> pd.DataFrame:
    return _gen_uptrend(days=days, daily_pct=-0.001, seed=seed)


def _gen_uptrend_with_panic(days: int = 260, seed: int = 11) -> pd.DataFrame:
    random.seed(seed)
    price = 100.0
    closes, vols = [], []
    # 253 days of steep uptrend so 200-MA stays well below
    for _ in range(days - 7):
        price *= (1 + 0.0018 + random.gauss(0, 0.005))
        closes.append(price)
        vols.append(1_000_000)
    # 7 days of sharp panic
    for _ in range(7):
        price *= (1 - 0.013)
        closes.append(price)
        vols.append(1_500_000)
    return _make_bars(closes, vols)


def _gen_tight_base_then_breakout(days: int = 260, seed: int = 23) -> pd.DataFrame:
    random.seed(seed)
    closes, vols = [], []
    base = 100.0
    for _ in range(days - 1):
        p = max(95, min(105, base * (1 + random.gauss(0, 0.012))))
        closes.append(p)
        vols.append(800_000 * (1 + random.uniform(-0.2, 0.2)))
    # Today: fresh 52w-high breakout on volume
    closes.append(110.0)
    vols.append(2_200_000)
    return _make_bars(closes, vols)


def _gen_random_noise(days: int = 260, seed: int = 99) -> pd.DataFrame:
    random.seed(seed)
    price = 100.0
    closes = []
    for _ in range(days):
        price *= (1 + random.gauss(0, 0.012))
        closes.append(price)
    return _make_bars(closes)


def _gen_benchmark(days: int = 260, seed: int = 1) -> pd.DataFrame:
    random.seed(seed)
    p = 100.0
    closes = []
    for _ in range(days):
        p *= (1 + 0.0006 + random.gauss(0, 0.004))
        closes.append(p)
    return _make_bars(closes)


@pytest.fixture(scope="module")
def benchmark() -> pd.DataFrame:
    return _gen_benchmark()


# ---------------------------------------------------------------------------
# Minervini-Lite
# ---------------------------------------------------------------------------

class TestMinerviniLite:
    def test_fires_on_clean_uptrend(self, benchmark):
        df = _gen_uptrend()
        sig = minervini_lite("TEST.NS", df, benchmark_df=benchmark)
        assert sig is not None
        assert sig.strategy == "minervini_lite"
        assert sig.action == "BUY"
        assert sig.score > 0

    def test_silent_on_downtrend(self, benchmark):
        df = _gen_downtrend()
        assert minervini_lite("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_on_random_noise(self, benchmark):
        df = _gen_random_noise()
        # Random walk — should not satisfy MA stack reliably
        assert minervini_lite("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_when_too_few_bars(self, benchmark):
        df = _gen_uptrend(days=100)
        assert minervini_lite("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_without_volume_thrust(self, benchmark):
        # Clean uptrend but with FLAT volume — should not fire
        random.seed(42)
        price = 100.0
        closes = []
        for _ in range(260):
            price *= (1 + 0.0012 + random.gauss(0, 0.005))
            closes.append(price)
        flat_vol = [1_000_000] * 260  # no recent thrust
        df = _make_bars(closes, flat_vol)
        sig = minervini_lite("TEST.NS", df, benchmark_df=benchmark)
        assert sig is None, f"should not fire without volume thrust, got: {sig}"

    def test_fires_on_panic_dip_kotegawa_target_does_not_fire_minervini(self, benchmark):
        df = _gen_uptrend_with_panic()
        # Minervini requires price > all MAs — broken by the panic
        assert minervini_lite("TEST.NS", df, benchmark_df=benchmark) is None


# ---------------------------------------------------------------------------
# Kotegawa Mean Reversion
# ---------------------------------------------------------------------------

class TestKotegawaMeanRev:
    def test_fires_on_panic_dip_in_uptrend(self, benchmark):
        df = _gen_uptrend_with_panic()
        sig = kotegawa_meanrev("TEST.NS", df, benchmark_df=benchmark)
        assert sig is not None
        assert sig.strategy == "kotegawa_meanrev"

    def test_silent_on_clean_uptrend(self, benchmark):
        df = _gen_uptrend()
        # No dip — should not fire
        assert kotegawa_meanrev("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_on_downtrend(self, benchmark):
        # 200-MA filter should reject (price < 200-MA)
        df = _gen_downtrend()
        assert kotegawa_meanrev("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_when_dip_breaks_uptrend(self, benchmark):
        # Mild uptrend + deep panic that breaks 200-MA — should reject (falling knife)
        random.seed(42)
        price = 100.0
        closes, vols = [], []
        for _ in range(252):
            price *= (1 + 0.001 + random.gauss(0, 0.005))
            closes.append(price)
            vols.append(1_000_000)
        # Big panic that breaks 200-MA
        for _ in range(8):
            price *= (1 - 0.025)
            closes.append(price)
            vols.append(1_500_000)
        df = _make_bars(closes, vols)
        assert kotegawa_meanrev("TEST.NS", df, benchmark_df=benchmark) is None


# ---------------------------------------------------------------------------
# Darvas Breakout
# ---------------------------------------------------------------------------

class TestDarvasBreakout:
    def test_fires_on_breakout_with_volume(self, benchmark):
        df = _gen_tight_base_then_breakout()
        sig = darvas_breakout("TEST.NS", df, benchmark_df=benchmark)
        assert sig is not None
        assert sig.strategy == "darvas_breakout"

    def test_silent_without_volume_thrust(self, benchmark):
        # Same breakout but with low volume — should NOT fire
        random.seed(23)
        closes, vols = [], []
        base = 100.0
        for _ in range(259):
            p = max(95, min(105, base * (1 + random.gauss(0, 0.012))))
            closes.append(p)
            vols.append(800_000)
        closes.append(110.0)
        vols.append(900_000)  # below 1.5x threshold
        df = _make_bars(closes, vols)
        assert darvas_breakout("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_on_clean_uptrend(self, benchmark):
        # No tight base — every recent day was a "new high" but range is too wide
        df = _gen_uptrend()
        assert darvas_breakout("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_on_downtrend(self, benchmark):
        df = _gen_downtrend()
        assert darvas_breakout("TEST.NS", df, benchmark_df=benchmark) is None

    def test_silent_when_too_few_bars(self, benchmark):
        df = _gen_tight_base_then_breakout(days=200)
        assert darvas_breakout("TEST.NS", df, benchmark_df=benchmark) is None


# ---------------------------------------------------------------------------
# Earnings warning soft-flag
# ---------------------------------------------------------------------------

class TestEarningsWarning:
    def test_warning_added_when_earnings_within_3_days(self, benchmark):
        df = _gen_uptrend()
        sig = minervini_lite("TEST.NS", df, benchmark_df=benchmark, earnings_days_away=2)
        assert sig is not None
        assert any("Earnings" in w for w in sig.warnings)

    def test_no_warning_when_earnings_far(self, benchmark):
        df = _gen_uptrend()
        sig = minervini_lite("TEST.NS", df, benchmark_df=benchmark, earnings_days_away=30)
        assert sig is not None
        assert sig.warnings == []

    def test_no_warning_when_earnings_unknown(self, benchmark):
        df = _gen_uptrend()
        sig = minervini_lite("TEST.NS", df, benchmark_df=benchmark, earnings_days_away=None)
        assert sig is not None
        assert sig.warnings == []
