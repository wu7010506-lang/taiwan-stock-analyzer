import json
from datetime import date
from pathlib import Path

from app.database import Database
from app.decision_history import capture_daily_decision_history


def test_daily_decision_history_keeps_market_and_evidence_references(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    monkeypatch.setattr("app.decision_history.build_daily_dashboard", lambda *_: {
        "as_of_date": "2026-07-29", "decision_gate": {"status": "caution"},
    })

    result = capture_daily_decision_history(
        database, {"market_score": 42, "regime": "risk_off"}, 7, date(2026, 7, 29)
    )
    stored = database.list_daily_decision_logs()

    assert result["quality_snapshot_id"] == 7
    assert json.loads(stored[0]["market_context_json"])["market_score"] == 42
    assert json.loads(stored[0]["payload_json"])["decision_gate"]["status"] == "caution"
