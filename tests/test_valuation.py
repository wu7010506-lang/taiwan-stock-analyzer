from datetime import date, timedelta
from decimal import Decimal

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.valuation import _decimal, analyze_valuations, sync_valuations


def test_valuation_decimal_handles_missing():
    assert _decimal("N/A") is None
    assert _decimal("-") is None
    assert float(_decimal("12.34")) == 12.34


def test_valuation_analysis_percentiles():
    rows = [
        {
            "symbol": "2330",
            "valuation_date": f"20260{index + 1}28",
            "pe_ratio": 10 + index,
            "pb_ratio": 2 + index / 10,
            "dividend_yield": 3 - index / 10,
            "financial_period": "115/1",
        }
        for index in range(6)
    ]
    result = analyze_valuations(rows)
    assert result["pe_ratio"] == 15
    assert result["pe_percentile"] == 100
    assert result["relative_valuation_band"] == "歷史相對高檔"
    assert result["observations"] == 6


def test_valuation_sync_uses_known_last_trading_day_once_per_month(tmp_path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    today = date.today()
    previous_month_end = today.replace(day=1) - timedelta(days=1)
    current_market_date = today
    database.upsert_prices([
        DailyPrice("2330", "TWSE", previous_month_end, Decimal("1"), Decimal("1"),
                   Decimal("1"), Decimal("1"), 1),
        DailyPrice("2330", "TWSE", current_market_date, Decimal("1"), Decimal("1"),
                   Decimal("1"), Decimal("1"), 1),
    ])
    calls = []

    def fake_fetch(client, symbol, market, target):
        calls.append(target)
        return {"symbol": symbol, "market": market,
                "valuation_date": target.strftime("%Y%m%d"), "pe_ratio": 10}

    monkeypatch.setattr("app.valuation.fetch_valuation_date", fake_fetch)
    start = previous_month_end.strftime("%Y-%m")
    result = sync_valuations(database, "2330", start, today.strftime("%Y-%m"))

    assert result["rows_written"] == 2
    assert calls == [previous_month_end, current_market_date]
