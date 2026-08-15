from datetime import date
from decimal import Decimal
from pathlib import Path

from app.data_quality import (_friendly_sync_error, build_data_quality_report,
                              vnext_history_coverage,
                              capture_data_quality_snapshot, evaluate_data_contracts)
from app.database import Database
from app.domain import DailyPrice, Instrument
from app.service import sync_market_data, sync_twse_candidate_price_fallback


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
    price_issue = next(
        issue for issue in report["issues"]
        if issue["code"] == "low_coverage" and issue.get("dataset") == "prices"
    )
    assert "1/2" in price_issue["detail"]
    assert report["quarantine"]["total_symbols"] == 1
    assert report["quarantine"]["groups"][0]["samples"][0]["symbol"] == "2454"
    assert report["contracts"]["status"] == "failed"


def test_vnext_history_coverage_explains_missing_research_prerequisites(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "Test", "TWSE", None)])

    coverage = vnext_history_coverage(database, target_limit=10, as_of_date=date(2026, 7, 29))

    assert coverage["status"] == "backfill_required"
    assert coverage["missing_counts"]["financial_history"] == 1
    assert coverage["missing_counts"]["price_history"] == 1


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
    assert 'id="quarantineRows"' in page.text
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


def test_market_sync_reports_successful_but_misaligned_market_dates_as_partial(
    tmp_path: Path, monkeypatch,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    monkeypatch.setattr("app.service.TwseProvider.fetch_instruments", lambda _: [])
    monkeypatch.setattr("app.service.TpexProvider.fetch_instruments", lambda _: [])
    monkeypatch.setattr(
        "app.service.TwseProvider.fetch_latest_prices",
        lambda _: [DailyPrice("2330", "TWSE", date(2026, 8, 10), Decimal("100"),
                              Decimal("101"), Decimal("99"), Decimal("100"), 1000)],
    )
    monkeypatch.setattr(
        "app.service.TpexProvider.fetch_latest_prices",
        lambda _: [DailyPrice("3105", "TPEx", date(2026, 8, 11), Decimal("50"),
                              Decimal("51"), Decimal("49"), Decimal("50"), 1000)],
    )

    result = sync_market_data(database)

    assert result["TWSE"]["data_date"] == "2026-08-10"
    assert result["TPEx"]["data_date"] == "2026-08-11"
    assert result["status"] == "partial"
    assert result["incomplete_markets"] == ["TWSE"]


def test_twse_candidate_fallback_uses_official_month_history_for_target_date(
    tmp_path: Path, monkeypatch,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()

    def history(_provider, symbol, _month):
        close = Decimal("100") if symbol == "2330" else Decimal("200")
        return [DailyPrice(symbol, "TWSE", date(2026, 8, 11), close, close,
                           close, close, 1000)]

    monkeypatch.setattr("app.service.TwseProvider.fetch_history_month", history)

    result = sync_twse_candidate_price_fallback(
        database, date(2026, 8, 11), symbols=["2330", "2454"], pause_seconds=0
    )

    assert result["status"] == "completed"
    assert result["source"] == "TWSE official per-symbol STOCK_DAY"
    assert result["requested_symbols"] == 2
    assert result["target_date_symbols"] == 2
    assert result["coverage_percent"] == 100.0
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM daily_prices WHERE market='TWSE' AND trade_date='2026-08-11'"
        ).fetchone()[0] == 2


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


def test_contract_rejects_stale_dataset_even_when_coverage_is_complete():
    contracts = evaluate_data_contracts({"TWSE": {"prices": {
        "coverage_percent": 100, "latest_date": "2026-07-01",
    }}}, as_of_date=date(2026, 7, 29))

    check = contracts["checks"][0]
    assert check["status"] == "failed"
    assert check["actual_age_days"] == 28


def test_contract_rejects_price_coverage_that_is_not_on_the_latest_market_date():
    contracts = evaluate_data_contracts({"TWSE": {"prices": {
        "coverage_percent": 100,
        "exact_date_coverage_percent": 17.5,
        "latest_date": "2026-08-13",
    }}}, as_of_date=date(2026, 8, 14))

    check = contracts["checks"][0]
    assert check["status"] == "failed"
    assert check["coverage_basis"] == "exact_latest_date"
    assert check["actual_coverage_percent"] == 17.5


def test_institution_contract_uses_recent_feed_cohort_not_all_listed_companies():
    contracts = evaluate_data_contracts({"TPEx": {"institutions": {
        "coverage_percent": 96.0,
        "exact_date_coverage_percent": 88.9,
        "exact_date_coverage_of_covered_percent": 92.6,
        "latest_date": "2026-08-13",
    }}}, as_of_date=date(2026, 8, 14))

    check = contracts["checks"][0]
    assert check["status"] == "passed"
    assert check["coverage_basis"] == "exact_latest_date_recent_cohort"
    assert check["actual_coverage_percent"] == 92.6
