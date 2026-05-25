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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import paper_trades
from app.data import fetch_history
from app.strategies import ALL_STRATEGIES, Signal
from app.universe import NIFTY_50, display_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="Indian Trading Alerts (Beginner MVP)")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------- Scan logic ----------

def _scan_one(ticker: str) -> list[dict[str, Any]]:
    df = fetch_history(ticker, period="1y")
    if df is None:
        return []
    out: list[Signal] = []
    for fn in ALL_STRATEGIES.values():
        sig = fn(ticker, df)
        if sig is not None:
            out.append(sig)
    return [asdict(s) | {"display": display_name(s.ticker)} for s in out]


async def _scan_universe() -> list[dict[str, Any]]:
    """Run all strategies across all tickers in parallel."""
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = await asyncio.gather(
            *[loop.run_in_executor(pool, _scan_one, t) for t in NIFTY_50]
        )
    flat = [sig for batch in results for sig in batch]
    flat.sort(key=lambda s: s["score"], reverse=True)
    return flat


# ---------- Routes ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "universe_size": len(NIFTY_50)},
    )


@app.get("/api/scan")
async def api_scan() -> JSONResponse:
    log.info("Scanning %d tickers...", len(NIFTY_50))
    signals = await _scan_universe()
    log.info("Scan complete: %d signals", len(signals))
    return JSONResponse({"count": len(signals), "signals": signals})


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
