from pathlib import Path

from app.database import Database
from app.domain import Instrument
from app.fundamental_batch import run_fundamental_batch


def test_batch_is_ranked_resumable_and_records_failures(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    instruments = [Instrument(str(1000 + index), f"S{index}", "TWSE", None)
                   for index in range(3)]
    database.upsert_instruments(instruments)
    with database.connect() as connection:
        for index, instrument in enumerate(instruments):
            connection.execute(
                """INSERT INTO daily_prices
                   (symbol,market,trade_date,open,high,low,close,volume,turnover)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (instrument.symbol, "TWSE", "2026-07-22", 10, 10, 10, 10,
                 1000, (index + 1) * 1000),
            )
    calls = []
    def fake_sync(_database, symbol, years):
        calls.append(symbol)
        if symbol == "1001":
            raise RuntimeError("provider error")
        return {"financial_rows_written": 20, "dividend_rows_written": 5}

    first = run_fundamental_batch(database, 10, 2, 5, synchronizer=fake_sync)
    assert calls == ["1002", "1001"]
    assert first["progress"]["completed"] == 1
    assert first["progress"]["failed"] == 1
    assert first["progress"]["pending"] == 1
    second = run_fundamental_batch(database, 10, 2, 5, synchronizer=fake_sync)
    assert calls[-1] == "1000"
    assert second["progress"]["completed"] == 2
    assert second["progress"]["pending"] == 0
