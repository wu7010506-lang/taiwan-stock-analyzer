from datetime import date
from decimal import Decimal

import pytest

from app.database import Database
from app.domain import DailyPrice, Instrument


def test_database_upsert_and_read(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "半導體業")])
    database.upsert_prices([
        DailyPrice("2330", "TWSE", date(2026, 7, 17), Decimal("1000"),
                   Decimal("1010"), Decimal("990"), Decimal("1005"), 10000)
    ])
    assert database.list_instruments("台積電")[0]["symbol"] == "2330"
    assert database.get_prices("2330")[0]["close"] == 1005
    assert database.get_prices("2330", start_date="2026-07-18") == []


def test_watchlist_persists_and_includes_quote(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "半導體業")])
    database.upsert_prices([
        DailyPrice("2330", "TWSE", date(2026, 7, 16), Decimal("990"),
                   Decimal("1000"), Decimal("980"), Decimal("990"), 9000),
        DailyPrice("2330", "TWSE", date(2026, 7, 17), Decimal("1000"),
                   Decimal("1010"), Decimal("990"), Decimal("1005"), 10000),
    ])
    database.add_to_watchlist("2330", "TWSE")
    assert database.is_watched("2330") is True
    row = database.list_watchlist()[0]
    assert row["name"] == "台積電"
    assert row["change_percent"] == pytest.approx(1005 / 990 - 1)
    assert database.remove_from_watchlist("2330") == 1
    assert database.is_watched("2330") is False


def test_popular_stocks_rank_latest_market_by_turnover(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2330", "台積電", "TWSE", "半導體業"),
        Instrument("2451", "創見", "TWSE", "半導體業"),
    ])
    database.upsert_prices([
        DailyPrice("2330", "TWSE", date(2026, 7, 20), Decimal("1000"),
                   Decimal("1010"), Decimal("990"), Decimal("1005"), 10000,
                   turnover=Decimal("9000000")),
        DailyPrice("2451", "TWSE", date(2026, 7, 20), Decimal("220"),
                   Decimal("225"), Decimal("210"), Decimal("221"), 50000,
                   turnover=Decimal("11000000")),
    ])
    rows = database.list_popular_stocks()
    assert [row["symbol"] for row in rows] == ["2451", "2330"]
    assert rows[0]["trade_date"] == "2026-07-20"


def test_popular_stocks_uses_most_complete_market_snapshot(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    instruments = [Instrument(str(1000 + index), f"公司{index}", "TWSE", "24") for index in range(3)]
    database.upsert_instruments(instruments)
    rows = [
        DailyPrice(item.symbol, "TWSE", date(2026, 7, 17), Decimal("10"),
                   Decimal("11"), Decimal("9"), Decimal("10"), 1000,
                   turnover=Decimal(1000000 + index))
        for index, item in enumerate(instruments)
    ]
    rows.append(DailyPrice("1000", "TWSE", date(2026, 7, 20), Decimal("10"),
                           Decimal("11"), Decimal("9"), Decimal("10"), 1000,
                           turnover=Decimal("9999999")))
    database.upsert_prices(rows)
    popular = database.list_popular_stocks(10)
    assert len(popular) == 3
    assert {row["trade_date"] for row in popular} == {"2026-07-17"}
