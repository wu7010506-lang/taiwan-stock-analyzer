from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.daily_sync import run_daily_close_sync
from app.database import Database


def should_run_daily_sync(now: datetime, latest_run: dict | None) -> bool:
    """Run once on Taiwan business days after the configured close-sync time."""
    if not settings.daily_sync_enabled or now.weekday() >= 5:
        return False
    if (now.hour, now.minute) < (settings.daily_sync_hour, settings.daily_sync_minute):
        return False
    if not latest_run:
        return True
    started = str(latest_run.get("started_at") or "")[:10]
    return started != now.date().isoformat()


async def daily_sync_loop(database: Database, stop: asyncio.Event) -> None:
    timezone = ZoneInfo(settings.daily_sync_timezone)
    while not stop.is_set():
        now = datetime.now(timezone)
        if should_run_daily_sync(now, database.get_latest_daily_sync_run()):
            await asyncio.to_thread(run_daily_close_sync, database)
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except TimeoutError:
            continue
