from fastapi.testclient import TestClient

from app import main


def test_mutating_routes_require_admin_key_when_enabled(monkeypatch):
    monkeypatch.setattr(main.settings, "require_admin_key", True)
    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(main, "sync_market_data", lambda _: {"status": "completed"})
    client = TestClient(main.app)

    assert client.post("/sync").status_code == 401
    assert client.post("/sync", headers={"X-Admin-Key": "wrong"}).status_code == 401
    allowed = client.post("/sync", headers={"X-Admin-Key": "test-secret"})
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "completed"


def test_openapi_marks_mutating_routes_as_api_key_protected():
    schema = main.app.openapi()

    schemes = schema["components"]["securitySchemes"]
    assert any(item.get("type") == "apiKey" for item in schemes.values())
    assert schema["paths"]["/sync"]["post"]["security"]
    assert schema["paths"]["/watchlist/{symbol}"]["put"]["security"]
