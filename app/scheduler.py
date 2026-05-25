"""Background scheduler that runs the scan automatically.

Default schedule: weekdays at 16:00 IST (30 minutes after NSE close at 15:30).
Override via env vars:
  SCAN_SCHEDULE_HOUR    (0-23, default 16)
  SCAN_SCHEDULE_MINUTE  (0-59, default 0)
  SCAN_SCHEDULE_DAYS    (cron day_of_week, default 'mon-fri')
  RUN_SCAN_ON_STARTUP   ('true' to trigger an immediate scan when the app
                         starts; useful for testing)

The scheduler runs in the same event loop as FastAPI via app.main's lifespan
hook. For 24/7 reliability you want this process to stay up (a small VM, a
container in your home lab, or a Render/Fly free tier).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import reports as reports_mod

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Type alias for the callable we expect from main.py
ScanFn = Callable[[], Awaitable[list[dict[str, Any]]]]


class ScanScheduler:
    """Daily scan scheduler with manual 'run now' support."""

    def __init__(self, scan_fn: ScanFn, universe_size_fn: Callable[[], int]):
        self._scan_fn = scan_fn
        self._universe_size_fn = universe_size_fn
        self._scheduler = AsyncIOScheduler(timezone=IST)
        self._last_run: Optional[dict[str, Any]] = None
        self._is_running = False
        self._lock = asyncio.Lock()

    # ---- lifecycle ----

    def start(self) -> None:
        hour = int(os.getenv("SCAN_SCHEDULE_HOUR", "16"))
        minute = int(os.getenv("SCAN_SCHEDULE_MINUTE", "0"))
        days = os.getenv("SCAN_SCHEDULE_DAYS", "mon-fri")

        self._scheduler.add_job(
            self._run_and_save,
            CronTrigger(day_of_week=days, hour=hour, minute=minute, timezone=IST),
            id="daily_scan",
            replace_existing=True,
            misfire_grace_time=3600,   # if missed (e.g. server was down), still run within 1h
            coalesce=True,             # collapse multiple missed runs into one
            max_instances=1,
        )
        self._scheduler.start()
        log.info(
            "Scheduler started: daily scan at %02d:%02d IST on %s",
            hour, minute, days,
        )

        if os.getenv("RUN_SCAN_ON_STARTUP", "").lower() == "true":
            log.info("RUN_SCAN_ON_STARTUP=true; kicking off an immediate scan.")
            asyncio.create_task(self.run_now())

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("Scheduler stopped.")

    # ---- run helpers ----

    async def run_now(self) -> dict[str, Any]:
        """Trigger a scan immediately and return the saved report."""
        async with self._lock:
            return await self._run_and_save()

    async def _run_and_save(self) -> dict[str, Any]:
        self._is_running = True
        try:
            log.info("Background scan starting...")
            t0 = time.perf_counter()
            signals = await self._scan_fn()
            duration = time.perf_counter() - t0
            report = reports_mod.build_report(
                signals,
                duration_s=duration,
                universe_size=self._universe_size_fn(),
            )
            reports_mod.save_report(report)
            self._last_run = {
                "scan_id": report["scan_id"],
                "scan_finished": report["scan_finished"],
                "total_signals": report["total_signals"],
                "duration_seconds": report["duration_seconds"],
            }
            log.info(
                "Background scan done: %d signals, %.1fs",
                len(signals), duration,
            )
            return report
        finally:
            self._is_running = False

    # ---- introspection ----

    @property
    def last_run(self) -> Optional[dict[str, Any]]:
        return self._last_run

    @property
    def is_running(self) -> bool:
        return self._is_running

    def next_run(self) -> Optional[str]:
        jobs = self._scheduler.get_jobs()
        if not jobs:
            return None
        nxt: Optional[datetime] = jobs[0].next_run_time
        return nxt.isoformat() if nxt else None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._scheduler.running,
            "is_scanning": self._is_running,
            "next_run": self.next_run(),
            "last_run": self._last_run,
        }
