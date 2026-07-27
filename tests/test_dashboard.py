from datetime import date
from pathlib import Path

from app.dashboard import build_daily_dashboard
from app.database import Database


def test_dashboard_keeps_other_sections_when_one_fails(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    monkeypatch.setattr("app.dashboard.build_data_quality_report",
                        lambda db: {"status": "healthy"})
    monkeypatch.setattr("app.dashboard.portfolio_summary",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("portfolio failed")))
    monkeypatch.setattr("app.dashboard.build_alerts", lambda *args: {"alerts": []})
    monkeypatch.setattr(database, "get_latest_vnext_recommendation_run", lambda: None)

    result = build_daily_dashboard(database, {"market_score": 50}, date(2026, 7, 27))

    assert result["portfolio"]["status"] == "unavailable"
    assert result["quality"]["status"] == "available"
    assert result["decision_gate"]["formal_actions_safe"] is True
    assert result["unavailable_sections"] == ["portfolio"]


def test_dashboard_page_is_available():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        page = client.get("/dashboard/")
        script = client.get("/static/dashboard.js")

    assert page.status_code == 200
    assert "今日投資決策" in page.text
    assert script.status_code == 200
    assert 'fetch("/dashboard")' in script.text


def test_dashboard_uses_persisted_vnext_snapshot(tmp_path: Path, monkeypatch):
    import json

    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.save_vnext_recommendation_run(
        "2026-07-24", json.dumps({"as_of_date": "2026-07-24", "recommendations": [
            {"symbol": "2330"}, {"symbol": "2454"}, {"symbol": "2317"},
            {"symbol": "2308"}, {"symbol": "2382"}, {"symbol": "9999"},
        ]}),
    )
    monkeypatch.setattr("app.dashboard.build_data_quality_report",
                        lambda db: {"status": "warning"})
    monkeypatch.setattr("app.dashboard.portfolio_summary", lambda *args: {})
    monkeypatch.setattr("app.dashboard.build_alerts", lambda *args: {})

    result = build_daily_dashboard(database, {}, date(2026, 7, 27))

    cached = result["recommendations"]["data"]
    assert cached["cached_snapshot_date"] == "2026-07-24"
    assert len(cached["recommendations"]) == 5
