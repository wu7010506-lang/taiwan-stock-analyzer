from datetime import date
from decimal import Decimal
from pathlib import Path

from app.data_quality import build_data_quality_report
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
    assert any(issue["code"] == "low_coverage" for issue in report["issues"])


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
    assert report.status_code == 200
    assert "markets" in report.json()


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
