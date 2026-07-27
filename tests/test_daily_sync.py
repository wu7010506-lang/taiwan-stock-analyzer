import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app import daily_sync
from app.database import Database
from app.domain import DailyPrice, Instrument
from app.sync_scheduler import should_run_daily_sync


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
    assert "data_freshness" in result["steps"]


def test_watchlist_sync_retries_only_when_first_attempt_is_partial(monkeypatch, tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    calls = []

    def fake_sync(_: Database):
        calls.append(True)
        return {"status": "partial" if len(calls) == 1 else "completed",
                "partial": 1 if len(calls) == 1 else 0, "stocks": 1,
                "completed": 0 if len(calls) == 1 else 1, "results": [], "failures": []}

    monkeypatch.setattr(daily_sync, "sync_watchlist_analysis_data", fake_sync)
    result = daily_sync._sync_watchlist_with_retry(database)

    assert len(calls) == 2
    assert result["status"] == "completed"
    assert result["retry_attempted"] is True
    assert result["retry_recovered"] == 1


def test_latest_daily_sync_handles_never_run(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    assert daily_sync.latest_daily_sync(database) == {"status": "never_run"}


def test_daily_sync_does_not_start_a_second_run_while_one_is_running(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()

    assert database.create_daily_sync_run() is not None
    assert database.create_daily_sync_run() is None


def test_daily_sync_recovers_a_stale_running_job(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    stale_id = database.create_daily_sync_run()
    with database.connect() as connection:
        connection.execute(
            "UPDATE daily_sync_runs SET started_at='2020-01-01 00:00:00' WHERE id=?",
            (stale_id,),
        )

    new_id = database.create_daily_sync_run(stale_after_minutes=60)

    assert new_id is not None
    with database.connect() as connection:
        stale = dict(connection.execute(
            "SELECT status,error,finished_at FROM daily_sync_runs WHERE id=?", (stale_id,)
        ).fetchone())
    assert stale["status"] == "failed"
    assert "stale running job" in stale["error"]
    assert stale["finished_at"] is not None


def test_daily_sync_persists_progress_between_steps(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    recorded = []
    original = database.update_daily_sync_progress

    def capture(run_id, payload):
        recorded.append(json.loads(payload))
        original(run_id, payload)

    monkeypatch.setattr(database, "update_daily_sync_progress", capture)
    monkeypatch.setattr(daily_sync, "sync_market_data", lambda db: {"status": "completed"})
    monkeypatch.setattr(daily_sync, "sync_screening_universe", lambda db: {"status": "completed"})
    monkeypatch.setattr(daily_sync, "sync_all_institutional_trades", lambda db: {"status": "completed"})
    monkeypatch.setattr(daily_sync, "_sync_watchlist_with_retry", lambda db: {"status": "completed"})
    monkeypatch.setattr(daily_sync, "_market_context_summary", lambda: {"status": "completed"})
    monkeypatch.setattr(daily_sync, "capture_recommendation_snapshots", lambda db, context: {"status": "completed"})
    monkeypatch.setattr(daily_sync, "get_market_context", lambda: {})

    daily_sync.run_daily_close_sync(database)

    assert any(snapshot.get("market", {}).get("status") == "running" for snapshot in recorded)
    assert any(snapshot.get("market", {}).get("status") == "completed" for snapshot in recorded)


def test_scheduler_runs_once_after_close_on_business_day(monkeypatch):
    monkeypatch.setattr("app.sync_scheduler.settings.daily_sync_enabled", True)
    monkeypatch.setattr("app.sync_scheduler.settings.daily_sync_hour", 15)
    monkeypatch.setattr("app.sync_scheduler.settings.daily_sync_minute", 10)
    now = datetime(2026, 7, 27, 15, 10)

    assert should_run_daily_sync(now, None) is True
    assert should_run_daily_sync(now, {"started_at": "2026-07-27 15:10:00"}) is False
    assert should_run_daily_sync(datetime(2026, 7, 27, 15, 9), None) is False
    assert should_run_daily_sync(datetime(2026, 7, 26, 15, 10), None) is False


def test_market_data_freshness_is_calculated_per_market(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2330", "台積電", "TWSE", "24"),
        Instrument("2454", "聯發科", "TWSE", "24"),
        Instrument("6488", "環球晶", "TPEx", "24"),
    ])
    database.upsert_prices([
        DailyPrice("2330", "TWSE", date(2026, 7, 24), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), 1000),
        DailyPrice("2454", "TWSE", date(2026, 7, 23), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), 1000),
        DailyPrice("6488", "TPEx", date(2026, 7, 23), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), 1000),
    ])

    freshness = database.get_market_data_freshness()

    assert freshness["TWSE"]["prices"] == {
        "latest_date": "2026-07-24", "covered_stocks": 2, "total_stocks": 2,
        "coverage_percent": 100.0, "stale_stocks": 0,
    }
    assert freshness["TPEx"]["prices"]["latest_date"] == "2026-07-23"
    assert freshness["TPEx"]["prices"]["coverage_percent"] == 100.0
