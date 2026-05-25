"""FastAPI application — entry point.

Run with:
    uvicorn app.main:app --reload

Then open http://localhost:8000.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import paper_trades, scan_history
from app.backtest import BacktestConfig, BacktestResult, run_backtest
from app.data import fetch_benchmark, fetch_history, next_earnings_days_away
from app.morning_brief import fetch_morning_brief
from app.strategies import ALL_STRATEGIES, Signal
from app.universe import display_name, get_universe, list_universes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

app = FastAPI(title="Indian Trading Alerts (Beginner MVP)")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------- Scan logic ----------

def _scan_one(ticker: str, benchmark_df) -> list[dict[str, Any]]:
    df = fetch_history(ticker, period="1y")
    if df is None:
        return []
    earn_days = next_earnings_days_away(ticker)
    out: list[Signal] = []
    for fn in ALL_STRATEGIES.values():
        sig = fn(ticker, df, benchmark_df=benchmark_df, earnings_days_away=earn_days)
        if sig is not None:
            out.append(sig)
    return [
        asdict(s) | {"display": display_name(s.ticker)}
        for s in out
    ]


async def _scan_universe(universe_name: str) -> list[dict[str, Any]]:
    """Run all strategies across all tickers in parallel."""
    tickers = get_universe(universe_name)
    benchmark_df = fetch_benchmark(period="1y")
    if benchmark_df is None:
        log.warning("Benchmark (^NSEI) fetch failed; relative-strength will be unavailable.")

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = await asyncio.gather(
            *[loop.run_in_executor(pool, _scan_one, t, benchmark_df) for t in tickers]
        )
    flat = [sig for batch in results for sig in batch]
    flat.sort(key=lambda s: s["score"], reverse=True)
    return flat


# ---------- Routes ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "universes": list_universes(),
        },
    )


@app.get("/api/universes")
async def api_universes() -> JSONResponse:
    return JSONResponse({"universes": list_universes()})


@app.get("/api/scan")
async def api_scan(universe: str = Query("NIFTY_50")) -> JSONResponse:
    tickers = get_universe(universe)
    log.info("Scanning %s (%d tickers)...", universe, len(tickers))
    signals = await _scan_universe(universe)
    log.info("Scan complete: %d signals", len(signals))
    scan_history.record_scan(universe, signals)
    return JSONResponse({
        "universe": universe,
        "universe_size": len(tickers),
        "count": len(signals),
        "signals": signals,
    })


@app.get("/api/morning-brief")
async def api_morning_brief() -> JSONResponse:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_morning_brief)
    return JSONResponse(data)


@app.get("/api/scan-history")
async def api_scan_history(limit: int = 25) -> JSONResponse:
    return JSONResponse({"history": scan_history.list_history(limit=limit)})


# ---------- backtest ----------

# In-process cache so the frontend can re-fetch a recent backtest cheaply.
_BACKTEST_CACHE: dict[str, BacktestResult] = {}


@app.post("/api/backtest")
async def api_backtest(body: dict[str, Any]) -> JSONResponse:
    """Run a backtest. Synchronous — may block 30s-3min depending on universe.

    Request body (all optional, sane defaults from BacktestConfig):
      { universe, years, starting_capital, risk_per_trade_pct,
        slippage_pct, brokerage_pct, cooldown_days }
    """
    try:
        cfg = BacktestConfig(
            universe=str(body.get("universe", "NIFTY_50")),
            years=int(body.get("years", 5)),
            starting_capital=float(body.get("starting_capital", 100_000)),
            risk_per_trade_pct=float(body.get("risk_per_trade_pct", 0.02)),
            slippage_pct=float(body.get("slippage_pct", 0.001)),
            brokerage_pct=float(body.get("brokerage_pct", 0.0005)),
            cooldown_days=int(body.get("cooldown_days", 10)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid backtest config: {exc}")

    log.info("Backtest requested: %s", cfg)
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, run_backtest, cfg)
    _BACKTEST_CACHE["last"] = result
    return JSONResponse(_result_to_dict(result))


@app.get("/api/backtest/last")
async def api_backtest_last() -> JSONResponse:
    """Return the most-recent backtest result if available."""
    last = _BACKTEST_CACHE.get("last")
    if last is None:
        return JSONResponse({"error": "no backtest run yet"}, status_code=404)
    return JSONResponse(_result_to_dict(last))


def _result_to_dict(r: BacktestResult) -> dict[str, Any]:
    """Convert dataclass to dict, capping the trade list for the API response."""
    from dataclasses import asdict
    d = asdict(r)
    # Trade list can be huge (thousands). Return only the last 200 to keep
    # the response readable; full list is logged server-side.
    if len(d.get("trades", [])) > 200:
        d["trades_truncated"] = True
        d["trades"] = d["trades"][-200:]
    return d


@app.get("/api/trades")
async def api_trades() -> JSONResponse:
    return JSONResponse({"trades": paper_trades.list_trades()})


@app.post("/api/trades")
async def api_add_trade(body: dict[str, Any]) -> JSONResponse:
    required = {"ticker", "action", "price", "qty"}
    if not required.issubset(body):
        raise HTTPException(400, f"Missing fields. Need: {required}")
    trade = paper_trades.add_trade(
        ticker=body["ticker"],
        action=body["action"],
        price=float(body["price"]),
        qty=int(body["qty"]),
        reason=str(body.get("reason", "")),
    )
    return JSONResponse(trade, status_code=201)


@app.post("/api/trades/{trade_id}/close")
async def api_close_trade(trade_id: str, body: dict[str, Any]) -> JSONResponse:
    if "exit_price" not in body:
        raise HTTPException(400, "exit_price required")
    trade = paper_trades.close_trade(trade_id, float(body["exit_price"]))
    if trade is None:
        raise HTTPException(404, "Trade not found or already closed")
    return JSONResponse(trade)
