from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import pytest

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.performance import model_performance


def test_performance_keeps_pending_separate_from_matured(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO recommendation_snapshots
               (snapshot_date,symbol,market,profile,model_version,rank,score,decision,
                close,factors_json,reasons_json,risks_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("2026-01-01", "2330", "TWSE", "evidence_based", "v1", 1, 80,
             "優先研究", 100, "{}", "[]", "[]"))
        connection.execute(
            """INSERT INTO recommendation_snapshots
               (snapshot_date,symbol,market,profile,model_version,rank,score,decision,
                close,factors_json,reasons_json,risks_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("2026-02-01", "2330", "TWSE", "evidence_based", "v1", 1, 80,
             "優先研究", 120, "{}", "[]", "[]"))
    database.upsert_prices([DailyPrice("2330", "TWSE", date(2026, 1, 1) + timedelta(days=i),
        Decimal(100 + i), Decimal(100 + i), Decimal(100 + i), Decimal(100 + i), 1000)
        for i in range(25)])
    result = model_performance(database, "evidence_based", 5, 65)
    assert result["total_signals"] == 2
    assert result["matured_signals"] == 1
    assert result["pending_signals"] == 1
    assert result["win_rate_percent"] == 100
    assert result["average_return_percent"] == pytest.approx(5)
