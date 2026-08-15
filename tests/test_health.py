from fastapi import Response

from app.main import app, health


def test_health_checks_database_scheduler_and_build_identity():
    class RunningTask:
        @staticmethod
        def done() -> bool:
            return False

    app.state.scheduler_task = RunningTask()
    response = Response()
    payload = health(response)

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["scheduler"] == "running"
    assert payload["version"] == "0.1.0"
    assert "build" in payload
    assert "latest_daily_sync" in payload
