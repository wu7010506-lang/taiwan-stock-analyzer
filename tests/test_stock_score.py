from datetime import date, timedelta
from decimal import Decimal

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.stock_score import score_stock


def test_stock_score_is_transparent_and_handles_partial_data(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    start = date(2026, 1, 1)
    database.upsert_prices([
        DailyPrice("2330", "TWSE", start + timedelta(days=index), Decimal(100 + index),
                   Decimal(102 + index), Decimal(99 + index), Decimal(101 + index), 10000)
        for index in range(65)
    ])
    result = score_stock(database, "2330")
    assert result["score"] is not None
    assert 0 <= result["score"] <= 100
    assert result["coverage"] < 100
    assert len(result["dimensions"]) == 5
    assert result["method_version"] == "transparent-score-v1"


def test_stock_score_returns_none_for_unknown_symbol(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    assert score_stock(database, "9999") is None
