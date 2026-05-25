"""Tiny JSON-backed paper trading log.

Stored in `paper_trades.json` next to the project root. Good enough for an MVP;
swap for SQLite later if needed.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

_LOG_PATH = Path("paper_trades.json")
_lock = Lock()


def _load() -> list[dict[str, Any]]:
    if not _LOG_PATH.exists():
        return []
    try:
        return json.loads(_LOG_PATH.read_text() or "[]")
    except json.JSONDecodeError:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    _LOG_PATH.write_text(json.dumps(items, indent=2))


def list_trades() -> list[dict[str, Any]]:
    with _lock:
        return _load()


def add_trade(
    ticker: str,
    action: str,
    price: float,
    qty: int,
    reason: str,
    strategy: str = "",
) -> dict[str, Any]:
    trade = {
        "id": str(uuid.uuid4())[:8],
        "ticker": ticker,
        "action": action.upper(),
        "price": round(float(price), 2),
        "qty": int(qty),
        "value": round(float(price) * int(qty), 2),
        "reason": reason,
        "strategy": strategy,           # which strategy triggered this entry
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "OPEN" if action.upper() == "BUY" else "CLOSED",
    }
    with _lock:
        items = _load()
        items.append(trade)
        _save(items)
    return trade


def list_open_trades() -> list[dict[str, Any]]:
    return [t for t in list_trades() if t.get("status") == "OPEN"]


def get_trade(trade_id: str) -> dict[str, Any] | None:
    for t in list_trades():
        if t["id"] == trade_id:
            return t
    return None


def close_trade(trade_id: str, exit_price: float) -> dict[str, Any] | None:
    with _lock:
        items = _load()
        for t in items:
            if t["id"] == trade_id and t["status"] == "OPEN":
                t["status"] = "CLOSED"
                t["exit_price"] = round(float(exit_price), 2)
                t["pnl"] = round((float(exit_price) - t["price"]) * t["qty"], 2)
                t["pnl_pct"] = round((float(exit_price) / t["price"] - 1) * 100, 2)
                t["closed_ts"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                _save(items)
                return t
    return None
