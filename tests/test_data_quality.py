from datetime import date
from decimal import Decimal
from pathlib import Path

from app.data_quality import (_friendly_sync_error, build_data_quality_report,
                              capture_data_quality_snapshot)
from app.database import Database
from app.domain import DailyPrice, Instrument
from app.service import sync_market_data


def test_data_quality_report_flags_low_market_coverage(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2330", "台積電", "TWSE", "24"),
        Instrument("2454", "聯發科", "TWSE", "24"),
    ])
    database.upsert_prices([
        DailyPrice("2330", "TWSE", date(2026, 7, 24), Decimal("100"),
                   Decimal("101"), Decimal("99"), Decimal("100"), 1000),
    ])

    report = build_data_quality_report(database)

    assert report["status"] == "critical"
    assert report["markets"]["TWSE"]["prices"]["coverage_percent"] == 50.0
    assert report["queues"]["fundamentals"]["universe_total"] == 2
    assert report["queues"]["fundamentals"]["full_market_initialized"] is False
    assert any(issue["code"] == "low_coverage" for issue in report["issues"])
    assert report["contracts"]["status"] == "failed"


def test_data_quality_snapshot_persists_contract_results(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])

    result = capture_data_quality_snapshot(database)
    snapshots = database.list_data_quality_snapshots()

    assert result["status"] == "completed"
    assert result["contracts"]["status"] == "failed"
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "critical"


def test_freshness_counts_current_instruments_within_dataset_tolerance(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2330", "台積電", "TWSE", "24"),
        Instrument("2454", "聯發科", "TWSE", "24"),
    ])
    database.upsert_prices([
        DailyPrice("2330", "TWSE", date(2026, 7, 24), Decimal("100"),
                   Decimal("101"), Decimal("99"), Decimal("100"), 1000),
        DailyPrice("2454", "TWSE", date(2026, 7, 20), Decimal("100"),
                   Decimal("101"), Decimal("99"), Decimal("100"), 1000),
        DailyPrice("9999", "TWSE", date(2026, 7, 24), Decimal("100"),
                   Decimal("101"), Decimal("99"), Decimal("100"), 1000),
    ])

    prices = database.get_market_data_freshness()["TWSE"]["prices"]

    assert prices["covered_stocks"] == 2
    assert prices["coverage_percent"] == 100.0
    assert prices["latest_date"] == "2026-07-24"


def test_data_quality_page_and_api_are_available():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        page = client.get("/data-quality/")
        report = client.get("/data-quality")

    assert page.status_code == 200
    assert "資料品質中心" in page.text
    assert 'id="snapshotQualityButton"' in page.text
    assert report.status_code == 200
    assert "markets" in report.json()
    assert client.post("/data-quality/snapshot").status_code == 200
    assert client.get("/data-quality/snapshots").status_code == 200


def test_market_sync_uses_explicit_cache_fallback(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])

    monkeypatch.setattr("app.service.TwseProvider.fetch_instruments",
                        lambda _: (_ for _ in ()).throw(RuntimeError("provider down")))
    monkeypatch.setattr("app.service.TpexProvider.fetch_instruments", lambda _: [])
    monkeypatch.setattr("app.service.TpexProvider.fetch_latest_prices", lambda _: [])

    result = sync_market_data(database)

    assert result["TWSE"]["fallback_used"] is True
    assert result["TWSE"]["status"] == "cached"
    assert result["TWSE"]["instruments"] == 1
    assert result["status"] == "partial"


def test_data_quality_report_exposes_source_policy_and_cached_fallback(tmp_path: Path):
    import json

    database = Database(tmp_path / "stocks.db")
    database.initialize()
    run_id = database.create_daily_sync_run()
    database.finish_daily_sync_run(
        run_id, "partial",
        json.dumps({"market": {"TWSE": {"fallback_used": True}}}), "market",
    )

    report = build_data_quality_report(database)

    assert any(row["dataset"] == "prices" for row in report["sources"])
    assert any(issue["code"] == "cached_fallback" for issue in report["issues"])


def test_quota_error_is_explained_in_user_friendly_chinese():
    message = _friendly_sync_error("FinMind public API quota is temporarily exhausted")

    assert "額度已用完" in message
    assert "自動續跑" in message


def test_resolved_watchlist_warning_is_not_kept_as_current_failure(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    database.add_to_watchlist("2330", "TWSE")
    run_id = database.create_daily_sync_run()
    database.finish_daily_sync_run(run_id, "partial", "{}", "watchlist_analysis")
    monkeypatch.setattr("app.data_quality.analysis_sync_plan", lambda *args: {"ready": True})

    report = build_data_quality_report(database)

    assert not any(issue["code"] == "daily_sync_incomplete" for issue in report["issues"])
    assert report["resolved_since_sync"]


def test_data_quality_escalates_terminal_dataset_sync_jobs(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.enqueue_data_sync_jobs("price_history", [{"symbol": "2330", "market": "TWSE"}])
    for _ in range(3):
        database.record_data_sync_attempt("price_history", "2330", "TWSE", error="source down")

    report = build_data_quality_report(database)

    assert report["queues"]["sync_jobs"]["terminal_failed"] == 1
    assert any(issue["code"] == "terminal_sync_jobs" for issue in report["issues"])


def test_data_quality_reports_repeated_provider_failure(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    for _ in range(3):
        database.record_data_source_health("test-source", "prices", error="down")

    report = build_data_quality_report(database)

    assert report["source_health"][0]["consecutive_failures"] == 3
    assert any(issue["code"] == "unhealthy_data_sources" for issue in report["issues"])
