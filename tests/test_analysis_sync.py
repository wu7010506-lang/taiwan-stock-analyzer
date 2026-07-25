from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.analysis_sync import analysis_sync_plan
from app.database import Database
from app.domain import DailyPrice, Instrument


def test_sync_plan_does_not_repeat_complete_price_history(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    start = date.today() - timedelta(days=160)
    database.upsert_prices([DailyPrice(
        "2330", "TWSE", start + timedelta(days=index), Decimal("100"),
        Decimal("101"), Decimal("99"), Decimal("100"), 1000,
    ) for index in range(161)])
    plan = analysis_sync_plan(database, "2330")
    assert plan["coverage"]["prices"]["ready"] is True
    assert "prices" not in plan["missing"]


def test_sync_plan_refreshes_stock_behind_market_date(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2330", "台積電", "TWSE", "24"),
        Instrument("2454", "聯發科", "TWSE", "24"),
    ])
    old = date.today() - timedelta(days=1)
    rows = [DailyPrice("2330", "TWSE", old - timedelta(days=index),
                       Decimal("100"), Decimal("101"), Decimal("99"),
                       Decimal("100"), 1000) for index in range(120)]
    rows.append(DailyPrice("2454", "TWSE", date.today(), Decimal("100"),
                           Decimal("101"), Decimal("99"), Decimal("100"), 1000))
    database.upsert_prices(rows)
    plan = analysis_sync_plan(database, "2330")
    assert plan["market_latest_date"] == date.today().isoformat()
    assert "prices" in plan["missing"]


def test_sync_plan_requires_history_when_only_latest_quotes_exist(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    today = date.today()
    database.upsert_prices([DailyPrice(
        "2330", "TWSE", today, Decimal("100"), Decimal("101"),
        Decimal("99"), Decimal("100"), 1000,
    )])
    assert "prices" in analysis_sync_plan(database, "2330")["missing"]
