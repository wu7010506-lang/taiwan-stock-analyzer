from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.fundamental_batch import run_fundamental_batch, run_price_history_batch


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


def test_full_market_queue_includes_stocks_without_price_rows(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2330", "台積電", "TWSE", None),
        Instrument("9999", "無行情公司", "TPEx", None),
    ])
    calls = []

    def fake_sync(_database, symbol, years):
        calls.append(symbol)
        return {"financial_rows_written": 20, "dividend_rows_written": 0}

    result = run_fundamental_batch(
        database, target_limit=None, batch_size=10, years=5,
        synchronizer=fake_sync,
    )

    assert set(calls) == {"2330", "9999"}
    assert result["progress"]["total"] == 2
    assert result["progress"]["remaining"] == 0


def test_quota_error_pauses_batch_without_consuming_remaining_jobs(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("1000", "A", "TWSE", None),
        Instrument("1001", "B", "TWSE", None),
    ])
    calls = []

    def quota_sync(_database, symbol, years):
        calls.append(symbol)
        raise RuntimeError("FinMind public API quota is temporarily exhausted")

    result = run_fundamental_batch(
        database, target_limit=None, batch_size=10, years=5,
        retry_failed=True, synchronizer=quota_sync,
    )

    assert len(calls) == 1
    assert result["quota_paused"] is True
    assert result["progress"]["pending"] == 1
    assert result["progress"]["failed"] == 1
    assert database.reset_failed_fundamental_syncs() == 0


def test_failed_batch_job_stops_retrying_after_three_attempts(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "A", "TWSE", None)])

    def failing_sync(*_args):
        raise RuntimeError("provider unavailable")

    for _ in range(3):
        run_fundamental_batch(database, None, 1, 5, retry_failed=True,
                              synchronizer=failing_sync)

    progress = database.get_fundamental_sync_progress()
    assert progress["failed"] == 1
    assert progress["terminal_failed"] == 1
    assert database.reset_failed_fundamental_syncs() == 0


def test_dataset_job_audit_keeps_attempt_history_and_terminal_failure(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    rows = [{"symbol": "1000", "market": "TWSE"}]
    database.enqueue_data_sync_jobs("financial_history", rows)
    for _ in range(3):
        database.record_data_sync_attempt("financial_history", "1000", "TWSE",
                                          error="provider unavailable", source="test")

    progress = database.get_data_sync_job_progress("financial_history")
    assert progress["terminal_failed"] == 1
    assert progress["failures"][0]["attempts"] == 3
    with database.connect() as connection:
        attempts = connection.execute("SELECT COUNT(*) FROM data_sync_attempts").fetchone()[0]
    assert attempts == 3


def test_source_health_resets_after_a_successful_attempt(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    for _ in range(3):
        database.record_data_source_health("provider", "prices", error="unavailable")
    assert database.get_data_source_health()[0]["consecutive_failures"] == 3

    database.record_data_source_health("provider", "prices", rows_written=4)

    health = database.get_data_source_health()[0]
    assert health["consecutive_failures"] == 0
    assert health["last_rows_written"] == 4


def test_full_market_price_queue_includes_stocks_without_current_prices(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2330", "A", "TWSE", None),
        Instrument("9999", "B", "TPEx", None),
    ])
    calls = []

    def fake_sync(_database, symbol, years):
        calls.append((symbol, years))
        _database.upsert_prices([
            DailyPrice(symbol, "TWSE" if symbol == "2330" else "TPEx",
                       date(2023, 1, 1) + timedelta(days=index),
                       Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1000)
            for index in range(650)
        ])
        return {"rows_written": 650}

    result = run_price_history_batch(
        database, target_limit=None, batch_size=10, years=3, synchronizer=fake_sync,
    )

    assert {symbol for symbol, _ in calls} == {"2330", "9999"}
    assert result["progress"]["total"] == 2
    assert result["progress"]["completed"] == 2


def test_short_listing_history_is_not_reported_as_a_source_failure(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("7769", "New", "TWSE", None)])

    def short_history(_database, symbol, _years):
        _database.upsert_prices([
            DailyPrice(symbol, "TWSE", date(2026, 1, 1) + timedelta(days=index),
                       Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), 1000)
            for index in range(120)
        ])
        return {"rows_written": 120, "source": "official"}

    result = run_price_history_batch(database, target_limit=None, batch_size=1,
                                     years=3, synchronizer=short_history)

    assert result["processed"][0]["status"] == "insufficient_history"
    assert result["progress"]["failed"] == 0
    assert result["progress"]["short_history"] == 1
