from datetime import date, timedelta
from decimal import Decimal

from app.alerts import _institution_streak, build_alerts
from app.database import Database
from app.domain import DailyPrice, Instrument


def test_institution_streak_counts_latest_direction():
    rows = [{"foreign_net": value} for value in [1000, -500, 2000, 3000, 4000]]
    assert _institution_streak(rows, "foreign_net") == (3, 9000)


def test_alert_center_monitors_watchlist_technical_signals(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    start = date(2026, 1, 1)
    database.upsert_prices([
        DailyPrice("2330", "TWSE", start + timedelta(days=index), Decimal(100 + index),
                   Decimal(102 + index), Decimal(99 + index), Decimal(101 + index), 10000)
        for index in range(65)
    ])
    database.add_to_watchlist("2330", "TWSE")
    result = build_alerts(database)
    assert result["stocks_monitored"] == 1
    assert any(item["title"] == "RSI 進入偏熱區" for item in result["alerts"])
    assert any(item["title"] == "接近已同步歷史高點" for item in result["alerts"])
