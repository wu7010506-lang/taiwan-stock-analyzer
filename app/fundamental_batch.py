from __future__ import annotations

from collections.abc import Callable

from app.database import Database
from app.historical_fundamentals import sync_historical_fundamentals
from app.historical_prices import sync_price_history_with_fallback


def run_fundamental_batch(
    database: Database, target_limit: int | None = 100, batch_size: int = 10, years: int = 5,
    retry_failed: bool = False,
    synchronizer: Callable[[Database, str, int], dict] = sync_historical_fundamentals,
) -> dict:
    universe = database.list_research_sync_universe(target_limit)
    database.prepare_fundamental_sync_queue(universe, years)
    database.enqueue_data_sync_jobs("financial_history", universe)
    if retry_failed:
        database.reset_retryable_data_sync_jobs("financial_history")
        database.reset_failed_fundamental_syncs()
    processed = []
    quota_paused = False
    for _ in range(batch_size):
        jobs = database.claim_fundamental_sync_batch(1)
        if not jobs:
            break
        job = jobs[0]
        try:
            result = synchronizer(database, job["symbol"], years)
            if result.get("financial_rows_written", 0) < 12:
                raise ValueError("Insufficient historical statements (fewer than 12 periods)")
            database.finish_fundamental_sync(job["symbol"], job["market"], result=result)
            database.record_data_sync_attempt(
                "financial_history", job["symbol"], job["market"],
                rows_written=result.get("financial_rows_written", 0), source="FinMind/MOPS",
            )
            database.record_data_source_health(
                "FinMind/MOPS", "financial_history",
                rows_written=result.get("financial_rows_written", 0),
            )
            processed.append({"symbol": job["symbol"], "status": "completed"})
        except Exception as exc:
            error = str(exc)[:500]
            database.finish_fundamental_sync(job["symbol"], job["market"], error=error)
            database.record_data_sync_attempt(
                "financial_history", job["symbol"], job["market"], error=error,
                source="FinMind/MOPS",
            )
            database.record_data_source_health("FinMind/MOPS", "financial_history", error=error)
            processed.append({"symbol": job["symbol"], "status": "failed", "error": error})
            if "quota" in error.lower():
                quota_paused = True
                break
    return {"target_limit": target_limit, "batch_size": batch_size, "years": years,
            "requests_per_stock": 4, "processed": processed,
            "quota_paused": quota_paused,
            "progress": database.get_fundamental_sync_progress(target_limit)}


def run_price_history_batch(
    database: Database, target_limit: int | None = 100, batch_size: int = 10, years: int = 3,
    retry_failed: bool = False,
    synchronizer: Callable[[Database, str, int], dict] = sync_price_history_with_fallback,
) -> dict:
    # The daily close job must progress across the whole listed universe.  Restricting
    # this queue to popular names leaves otherwise eligible companies permanently
    # unable to satisfy the vNext price-history contract.
    universe = (database.list_research_sync_universe(None) if target_limit is None
                else database.list_popular_stocks(target_limit))
    database.prepare_price_sync_queue(universe)
    database.enqueue_data_sync_jobs("price_history", universe)
    if retry_failed:
        database.reset_retryable_data_sync_jobs("price_history")
        database.reset_failed_price_syncs()
    processed = []
    for job in database.claim_price_sync_batch(batch_size):
        try:
            result = synchronizer(database, job["symbol"], years)
            total_rows = len(database.get_prices(job["symbol"], 5000))
            if total_rows < 500:
                database.finish_price_sync(
                    job["symbol"], job["market"], total_rows, status="short_history"
                )
                database.record_data_sync_attempt(
                    "price_history", job["symbol"], job["market"],
                    rows_written=result.get("rows_written", 0),
                    source=result.get("source") or "FinMind",
                )
                database.record_data_source_health(
                    result.get("source") or "FinMind", "price_history",
                    rows_written=result.get("rows_written", 0),
                )
                processed.append({"symbol": job["symbol"], "status": "insufficient_history",
                                  "rows": total_rows,
                                  "reason": "fewer_than_500_trading_days"})
                continue
            database.finish_price_sync(job["symbol"], job["market"], total_rows)
            database.record_data_sync_attempt(
                "price_history", job["symbol"], job["market"],
                rows_written=result.get("rows_written", 0),
                source=result.get("source") or "FinMind",
            )
            database.record_data_source_health(
                result.get("source") or "FinMind", "price_history",
                rows_written=result.get("rows_written", 0),
            )
            processed.append({"symbol": job["symbol"], "status": "completed",
                              "rows": result.get("rows_written", 0)})
        except Exception as exc:
            error = str(exc)[:500]
            database.finish_price_sync(job["symbol"], job["market"], error=error)
            database.record_data_sync_attempt(
                "price_history", job["symbol"], job["market"], error=error,
                source="FinMind/TWSE/TPEx",
            )
            database.record_data_source_health("FinMind/TWSE/TPEx", "price_history", error=error)
            processed.append({"symbol": job["symbol"], "status": "failed", "error": error})
    return {"target_limit": target_limit, "batch_size": batch_size, "years": years,
            "requests_per_stock": 1, "processed": processed,
            "progress": database.get_price_sync_progress(target_limit)}
