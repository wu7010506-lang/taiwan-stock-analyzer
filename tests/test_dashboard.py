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


def test_dashboard_page_redirects_to_recommendations():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        page = client.get("/dashboard/", follow_redirects=False)
        script = client.get("/static/dashboard.js")

    assert page.status_code == 307
    assert page.headers["location"] == "/recommendations/"
    return
    assert "今日投資決策" in page.text
    assert script.status_code == 200
    assert 'fetch("/dashboard")' in script.text
    assert "(portfolio.watching_decisions || [])" in script.text
    assert ".slice(0,8)" not in script.text
    assert "watchingDecisionDetail" in script.text
    assert "decision.risks" in script.text


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
    assert cached["recommendations"][0]["technical_timing"]["status"] == "insufficient_data"
    assert cached["recommendations"][0]["model_action"] is None
    observations = result["short_term"]["data"]["model_observations"]
    assert len(observations) == 5
    assert observations[0]["symbol"] == "2330"
    assert observations[0]["action"] == "observation"
    assert observations[0]["source"] == "vnext_formal_model"


def test_short_history_observation_never_suggests_an_entry():
    from app.portfolio import _watching_decision

    decision = _watching_decision(
        {"model": "vnext_observation", "action": "buy", "value_score": 80,
         "supporting_reasons": ["recent_financials_available"], "risks": []},
        {}, {"id": "risk_off", "max_new_allocation_percent": 2},
    )

    assert decision["action"] == "insufficient_data"
    assert decision["new_allocation_percent"] == 0
