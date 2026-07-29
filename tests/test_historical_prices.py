from datetime import date
from pathlib import Path

from app.database import Database
from app.domain import Instrument
from app import historical_prices


def test_price_history_uses_official_exchange_when_finmind_fails(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "A", "TWSE", None)])
    monkeypatch.setattr(historical_prices, "sync_finmind_price_history",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("quota")))
    monkeypatch.setattr(historical_prices, "sync_history", lambda *_: {
        "status": "completed", "rows_written": 650,
    })

    result = historical_prices.sync_price_history_with_fallback(database, "2330", 3)

    assert result["fallback_used"] is True
    assert result["source"] == "TWSE/TPEx official history fallback"
    assert "quota" in result["primary_error"]
