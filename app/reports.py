"""Scan report generation and persistence.

Each scan run produces:
  - reports/<scan_id>.json - full machine-readable report
  - reports/<scan_id>.md   - human-readable Markdown summary

Reports are surfaced in the dashboard's Reports tab and via the
/api/reports endpoint.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.strategies import ALL_STRATEGIES

log = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")
IST = timezone(timedelta(hours=5, minutes=30))

# Friendly labels mirroring the dashboard badges
STRATEGY_LABELS: dict[str, str] = {
    "minervini_lite":   "Trend (Minervini)",
    "kotegawa_meanrev": "Mean Reversion (BNF)",
    "bnf_classic":      "BNF Classic",
    "darvas_box":       "Darvas Box",
    "turtle_breakout":  "Turtle 20-day",
    "livermore_pivot":  "Livermore Pivot",
    "zanger_breakout":  "Zanger Volume",
    "qullamaggie_ep":   "Episodic Pivot (Qullamaggie)",
}


# ---------- build ----------

def build_report(
    signals: list[dict[str, Any]],
    duration_s: float,
    universe_size: int,
    exit_alerts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Group signals by strategy and rank top picks. Pure function (no I/O)."""
    now = datetime.now(IST)
    exit_alerts = exit_alerts or []

    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sig in signals:
        by_strategy[sig["strategy"]].append(sig)

    # Ensure every registered strategy appears (even with 0 hits)
    for key in ALL_STRATEGIES:
        by_strategy.setdefault(key, [])

    # Sort hits within each strategy by score
    for hits in by_strategy.values():
        hits.sort(key=lambda s: s["score"], reverse=True)

    top_picks = sorted(signals, key=lambda s: s["score"], reverse=True)[:5]

    return {
        "scan_id": now.strftime("%Y%m%d-%H%M%S"),
        "scan_finished": now.isoformat(),
        "universe_size": universe_size,
        "duration_seconds": round(duration_s, 1),
        "total_signals": len(signals),
        "total_exit_alerts": len(exit_alerts),
        "strategy_hit_counts": {k: len(v) for k, v in by_strategy.items()},
        "by_strategy": dict(by_strategy),
        "top_picks": top_picks,
        "exit_alerts": exit_alerts,
    }


# ---------- persist ----------

def save_report(report: dict[str, Any]) -> Path:
    """Persist as both JSON and Markdown. Returns the JSON path."""
    REPORTS_DIR.mkdir(exist_ok=True)
    scan_id = report["scan_id"]
    json_path = REPORTS_DIR / f"{scan_id}.json"
    md_path = REPORTS_DIR / f"{scan_id}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    md_path.write_text(report_to_markdown(report))
    log.info(
        "Saved report %s: %d signals, %ss",
        scan_id, report["total_signals"], report["duration_seconds"],
    )
    return json_path


# ---------- read ----------

def list_reports(limit: int = 30) -> list[dict[str, Any]]:
    """Return summary metadata for recent reports, newest first."""
    if not REPORTS_DIR.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for path in sorted(REPORTS_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        summaries.append({
            "scan_id": data.get("scan_id", path.stem),
            "scan_finished": data.get("scan_finished"),
            "total_signals": data.get("total_signals", 0),
            "duration_seconds": data.get("duration_seconds", 0),
            "strategy_hit_counts": data.get("strategy_hit_counts", {}),
        })
    return summaries


def get_report(scan_id: str) -> Optional[dict[str, Any]]:
    """Load a single full report by scan_id."""
    # Defend against path traversal: scan_id is generated from datetime,
    # so any non-alnum/dash input is rejected.
    if not all(c.isalnum() or c == "-" for c in scan_id):
        return None
    path = REPORTS_DIR / f"{scan_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


# ---------- markdown rendering ----------

def report_to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    ts = report.get("scan_finished", "")
    lines.append(f"# Nifty 50 Scan Report")
    lines.append("")
    lines.append(f"- **Finished:** {ts}")
    lines.append(f"- **Universe:** {report['universe_size']} stocks")
    lines.append(f"- **Duration:** {report['duration_seconds']}s")
    lines.append(
        f"- **New BUY signals:** {report['total_signals']} across "
        f"{len(ALL_STRATEGIES)} strategies"
    )
    lines.append(
        f"- **SELL alerts (open trades):** "
        f"{report.get('total_exit_alerts', 0)}"
    )
    lines.append("")

    # ---- SELL alerts (most urgent, show first) ----
    exit_alerts = report.get("exit_alerts", [])
    if exit_alerts:
        lines.append("## SELL alerts on your open trades")
        lines.append("")
        lines.append("| Ticker | Strategy | Type | Entry | Now | P&L % | Why |")
        lines.append("|---|---|---|---:|---:|---:|---|")
        for ex in exit_alerts:
            label = STRATEGY_LABELS.get(ex["strategy"], ex["strategy"])
            ticker = ex["ticker"].replace(".NS", "")
            reason = ex["reason"].replace("\n", " ").replace("|", "/")
            if len(reason) > 200:
                reason = reason[:197] + "..."
            lines.append(
                f"| {ticker} | {label} | {ex['exit_type']} | "
                f"Rs.{ex['entry_price']:.2f} | Rs.{ex['current_price']:.2f} | "
                f"{ex['pnl_pct']:+.1f}% | {reason} |"
            )
        lines.append("")

    # ---- Hit counts table ----
    lines.append("## New BUY signals - hit counts")
    lines.append("")
    lines.append("| Strategy | Hits |")
    lines.append("|---|---:|")
    for key in ALL_STRATEGIES:
        label = STRATEGY_LABELS.get(key, key)
        hits = report["strategy_hit_counts"].get(key, 0)
        lines.append(f"| {label} | {hits} |")
    lines.append("")

    # ---- Top picks ----
    if report["top_picks"]:
        lines.append("## Top picks (by score)")
        lines.append("")
        for i, sig in enumerate(report["top_picks"], 1):
            label = STRATEGY_LABELS.get(sig["strategy"], sig["strategy"])
            lines.append(
                f"**{i}. {sig['display']}** - {label} - "
                f"Rs.{sig['price']:.2f} (score {sig['score']:.2f})"
            )
            lines.append("")
            lines.append(f"> {sig['reason']}")
            lines.append("")

    # ---- Per-strategy detail ----
    lines.append("## By strategy")
    lines.append("")
    for key in ALL_STRATEGIES:
        label = STRATEGY_LABELS.get(key, key)
        hits = report["by_strategy"].get(key, [])
        lines.append(f"### {label} - {len(hits)} hit(s)")
        lines.append("")
        if not hits:
            lines.append("_No candidates._")
            lines.append("")
            continue
        lines.append("| Ticker | Price | Score | Reason |")
        lines.append("|---|---:|---:|---|")
        for sig in hits:
            reason = (
                sig["reason"]
                .replace("\n", " ")
                .replace("|", "/")
            )
            if len(reason) > 240:
                reason = reason[:237] + "..."
            lines.append(
                f"| {sig['display']} | Rs.{sig['price']:.2f} | "
                f"{sig['score']:.2f} | {reason} |"
            )
        lines.append("")

    return "\n".join(lines)
