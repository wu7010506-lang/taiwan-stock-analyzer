from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.daily_sync import run_daily_close_sync
from app.database import Database


def should_run_daily_sync(now: datetime, latest_run: dict | None) -> bool:
    """Run once on Taiwan business days after the configured close-sync time."""
    if not settings.daily_sync_enabled:
        return False
    started_text = str((latest_run or {}).get("started_at") or "")
    latest_status = (latest_run or {}).get("status")
    if started_text and latest_status in {"partial", "failed"}:
        try:
            previous = datetime.fromisoformat(started_text)
            if now.tzinfo is not None and previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc).astimezone(now.tzinfo)
            if previous.date() < now.date():
                return True
        except ValueError:
            pass
    if now.weekday() >= 5 and started_text and latest_status in {"partial", "failed"}:
        try:
            steps = json.loads(str((latest_run or {}).get("steps_json") or "{}"))
            market_step = steps.get("market") or {}
            target_text = str(market_step.get("target_data_date") or "")
            target_date = datetime.fromisoformat(target_text).date()
            previous_utc = datetime.fromisoformat(started_text).replace(tzinfo=timezone.utc)
            elapsed_minutes = (
                now.astimezone(timezone.utc) - previous_utc
            ).total_seconds() / 60
            # SQLite stores UTC timestamps.  A late Friday run can therefore look
            # like a Saturday run after timezone conversion and be skipped by the
            # weekend guard.  Retry it once after Saturday morning, when the
            # exchange's delayed bulk file is normally available.
            if (
                now.hour >= 8
                and market_step.get("status") in {"partial", "failed"}
                and target_date < now.date()
                and started_text[:10] < now.date().isoformat()
                and elapsed_minutes >= settings.daily_sync_retry_minutes
            ):
                return True
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if now.weekday() >= 5:
        return False
    if (now.hour, now.minute) < (settings.daily_sync_hour, settings.daily_sync_minute):
        return False
    if not latest_run:
        return True
    if started_text[:10] != now.date().isoformat():
        return True
    # Older rows written before run status was persisted represent a completed
    # daily run.  Only explicit partial/failed runs are eligible for a retry.
    if latest_run.get("status") not in {"partial", "failed"}:
        return False
    try:
        previous = datetime.fromisoformat(started_text).replace(tzinfo=timezone.utc)
        elapsed_minutes = (now.astimezone(timezone.utc) - previous).total_seconds() / 60
        return elapsed_minutes >= settings.daily_sync_retry_minutes
    except ValueError:
        return False


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
