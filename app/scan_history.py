"""Persists each scan run to disk so we can later answer 'did this signal work?'.

Stored in `scan_history.json` next to the project root. Each entry has:
- ts (ISO timestamp)
- universe (NIFTY_50, NIFTY_100, etc.)
- signal_count
- signals (list of dicts as returned by /api/scan)

Capped at the most-recent N entries to keep the file manageable.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

_PATH = Path("scan_history.json")
_lock = Lock()
_MAX_ENTRIES = 200


def _load() -> list[dict[str, Any]]:
    if not _PATH.exists():
        return []
    try:
        return json.loads(_PATH.read_text() or "[]")
    except json.JSONDecodeError:
        return []


def _save(items: list[dict[str, Any]]) -> None:
    _PATH.write_text(json.dumps(items[-_MAX_ENTRIES:], indent=2))


def record_scan(universe: str, signals: list[dict[str, Any]]) -> dict[str, Any]:
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "universe": universe,
        "signal_count": len(signals),
        "signals": signals,
    }
    with _lock:
        items = _load()
        items.append(entry)
        _save(items)
    return entry


def list_history(limit: int = 50) -> list[dict[str, Any]]:
    """Return most-recent scan records (newest first)."""
    with _lock:
        items = _load()
    return list(reversed(items))[:limit]
