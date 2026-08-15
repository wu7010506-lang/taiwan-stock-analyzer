from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.analysis_sync import _incomplete_coverage_reason, analysis_sync_plan
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


def test_sync_plan_refreshes_revenue_behind_market_month(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2301", "Lite-On", "TWSE", "25"),
        Instrument("2408", "Nanya Tech", "TWSE", "24"),
    ])
    with database.connect() as connection:
        for month in range(10):
            connection.execute(
                """INSERT INTO monthly_revenues
                   (symbol,market,revenue_month,revenue)
                   VALUES('2301','TWSE',?,1000)""",
                (f"2025-{9 + month:02d}" if month < 4 else f"2026-{month - 3:02d}",),
            )
        connection.execute(
            """INSERT INTO monthly_revenues
               (symbol,market,revenue_month,revenue)
               VALUES('2408','TWSE','2026-07',1000)"""
        )

    plan = analysis_sync_plan(database, "2301")

    assert plan["coverage"]["revenues"]["market_latest_date"] == "2026-07"
    assert plan["coverage"]["revenues"]["latest_date"] == "2026-06"
    assert "revenues" in plan["missing"]


def test_sync_plan_refreshes_end_of_day_data_behind_latest_price(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2301", "Lite-On", "TWSE", "25")])
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO daily_prices
               (symbol,market,trade_date,open,high,low,close,volume)
               VALUES('2301','TWSE','2026-08-11',100,101,99,100,1000)"""
        )
        connection.execute(
            """INSERT INTO valuations(symbol,market,valuation_date,pe_ratio)
               VALUES('2301','TWSE','20260810',20)"""
        )
        connection.execute(
            """INSERT INTO institutional_trades
               (symbol,market,trade_date,foreign_buy,foreign_sell,foreign_net,
                trust_buy,trust_sell,trust_net,source)
               VALUES('2301','TWSE','2026-08-10',0,0,0,0,0,0,'official')"""
        )

    plan = analysis_sync_plan(database, "2301")

    assert "valuations" in plan["missing"]
    assert "institutions" in plan["missing"]


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


def test_incomplete_coverage_reason_explains_a_silent_sync_shortfall():
    reason = _incomplete_coverage_reason("revenues", {"rows": 1, "latest_date": "2026-06"})

    assert "revenues" in reason
    assert "rows=1" in reason
    assert "2026-06" in reason


def test_recent_limited_history_does_not_retry_forever(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2072", "新上市", "TWSE", "24")])
    today = date.today()
    database.upsert_prices([DailyPrice(
        "2072", "TWSE", today, Decimal("100"), Decimal("101"),
        Decimal("99"), Decimal("100"), 1000,
    )])
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO analysis_sync_state(symbol,dataset,last_attempt,status,error)
               VALUES('2072','prices',CURRENT_TIMESTAMP,'limited','short history')"""
        )

    plan = analysis_sync_plan(database, "2072")

    assert "prices" not in plan["missing"]
    assert plan["coverage"]["prices"]["ready"] is True
    assert plan["coverage"]["prices"]["history_sufficient"] is False
def test_watchlist_batch_is_bounded_and_reports_deferred_stocks(tmp_path: Path, monkeypatch):
    from app import analysis_sync
    from app.domain import Instrument

    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument(f"{index:04d}", f"Stock {index}", "TWSE", None)
        for index in range(25)
    ])
    for index in range(25):
        database.add_to_watchlist(f"{index:04d}", "TWSE")
    calls = []
    monkeypatch.setattr(
        analysis_sync, "sync_missing_analysis_data",
        lambda _database, symbol: calls.append(symbol) or {
            "status": "completed", "requested": [], "remaining": [], "results": {},
        },
    )

    result = analysis_sync.sync_watchlist_analysis_data(database, max_stocks=20)

    assert len(calls) == 20
    assert result["total_stocks"] == 25
    assert result["deferred"] == 5
