from __future__ import annotations

from collections.abc import Callable

from app.database import Database
from app.historical_fundamentals import sync_historical_fundamentals
from app.historical_prices import sync_finmind_price_history


def run_fundamental_batch(
    database: Database, target_limit: int = 100, batch_size: int = 10, years: int = 5,
    retry_failed: bool = False,
    synchronizer: Callable[[Database, str, int], dict] = sync_historical_fundamentals,
) -> dict:
    universe = database.list_popular_stocks(target_limit)
    database.prepare_fundamental_sync_queue(universe, years)
    if retry_failed:
        database.reset_failed_fundamental_syncs()
    processed = []
    for job in database.claim_fundamental_sync_batch(batch_size):
        try:
            result = synchronizer(database, job["symbol"], years)
            if result.get("financial_rows_written", 0) < 12:
                raise ValueError("Insufficient historical statements (fewer than 12 periods)")
            database.finish_fundamental_sync(job["symbol"], job["market"], result=result)
            processed.append({"symbol": job["symbol"], "status": "completed"})
        except Exception as exc:
            error = str(exc)[:500]
            database.finish_fundamental_sync(job["symbol"], job["market"], error=error)
            processed.append({"symbol": job["symbol"], "status": "failed", "error": error})
    return {"target_limit": target_limit, "batch_size": batch_size, "years": years,
            "requests_per_stock": 4, "processed": processed,
            "progress": database.get_fundamental_sync_progress(target_limit)}


def run_price_history_batch(
    database: Database, target_limit: int = 100, batch_size: int = 10, years: int = 3,
    retry_failed: bool = False,
    synchronizer: Callable[[Database, str, int], dict] = sync_finmind_price_history,
) -> dict:
    universe = database.list_popular_stocks(target_limit)
    database.prepare_price_sync_queue(universe)
    if retry_failed:
        database.reset_failed_price_syncs()
    processed = []
    for job in database.claim_price_sync_batch(batch_size):
        try:
            result = synchronizer(database, job["symbol"], years)
            total_rows = len(database.get_prices(job["symbol"], 5000))
            if total_rows < 500:
                raise ValueError("Historical prices remain below 500 trading days")
            database.finish_price_sync(job["symbol"], job["market"], total_rows)
            processed.append({"symbol": job["symbol"], "status": "completed",
                              "rows": result.get("rows_written", 0)})
        except Exception as exc:
            error = str(exc)[:500]
            database.finish_price_sync(job["symbol"], job["market"], error=error)
            processed.append({"symbol": job["symbol"], "status": "failed", "error": error})
    return {"target_limit": target_limit, "batch_size": batch_size, "years": years,
            "requests_per_stock": 1, "processed": processed,
            "progress": database.get_price_sync_progress(target_limit)}
