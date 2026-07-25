import json
from pathlib import Path

from app import daily_sync
from app.database import Database


def test_daily_sync_records_independent_step_results(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    monkeypatch.setattr(daily_sync, "sync_market_data", lambda db: {"status": "completed"})
    monkeypatch.setattr(daily_sync, "sync_screening_universe",
                        lambda db: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(daily_sync, "sync_all_institutional_trades",
                        lambda db: {"status": "completed", "rows_written": 10})
    monkeypatch.setattr(daily_sync, "get_market_context",
                        lambda force=False: {"status": "completed", "market_score": 55})
    result = daily_sync.run_daily_close_sync(database)
    assert result["status"] == "partial"
    latest = database.get_latest_daily_sync_run()
    assert latest["status"] == "partial"
    assert json.loads(latest["steps_json"])["fundamentals"]["status"] == "failed"


def test_latest_daily_sync_handles_never_run(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    assert daily_sync.latest_daily_sync(database) == {"status": "never_run"}
