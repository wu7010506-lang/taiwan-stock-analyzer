from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.portfolio import PositionUpdate, portfolio_summary


def test_portfolio_calculates_profit_and_risk_flags(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    database.add_to_watchlist("2330", "TWSE")
    database.upsert_prices([DailyPrice("2330", "TWSE", date(2026, 7, 22),
        Decimal(120), Decimal(121), Decimal(119), Decimal(120), 1000)])
    assert database.update_watchlist_position("2330", {"average_cost": 100, "shares": 1000,
        "purchase_date": "2026-01-01", "stop_loss": 90, "target_price": 115,
        "investment_horizon": "long", "notes": "test"})
    result = portfolio_summary(database)
    assert result["held_count"] == 1
    assert result["total_cost"] == 100_000
    assert result["total_market_value"] == 120_000
    assert result["unrealized_return_percent"] == pytest.approx(20)
    assert result["positions"][0]["target_reached"] is True
    assert any("目標價" in warning for warning in result["warnings"])


def test_position_requires_cost_when_shares_are_held():
    with pytest.raises(ValueError):
        PositionUpdate(shares=1000)
