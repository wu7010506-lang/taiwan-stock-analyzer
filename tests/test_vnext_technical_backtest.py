from datetime import date, timedelta
from pathlib import Path

from app.database import Database
from app.vnext_backtest import _context_as_of


def test_historical_context_exposes_only_index_return_known_at_signal_date(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    start = date(2026, 1, 1)
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO market_index_snapshots(trade_date,close,market_score,overheat_score,regime) VALUES(?,?,?,?,?)",
            [((start + timedelta(days=index)).isoformat(), 100 + index, 55, 10, "neutral")
             for index in range(21)],
        )
    context = _context_as_of(database, "2026-01-21")

    assert context["as_of"] == "2026-01-21"
    assert context["index_change_20d"] == 20
    assert context["historical_context_available"] is True
