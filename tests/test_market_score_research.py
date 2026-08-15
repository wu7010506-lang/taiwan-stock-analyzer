from datetime import date, timedelta
from pathlib import Path

from app.database import Database
from app.market_score_research import validate_market_score


def test_market_score_validation_uses_only_prior_index_closes(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO market_index_snapshots(trade_date,close) VALUES(?,?)",
            [((date(2024, 1, 1) + timedelta(days=index)).isoformat(), 100 + index * .2)
             for index in range(150)],
        )

    result = validate_market_score(database)

    assert result["formal_recommendation_allowed"] is False
    assert result["thresholds"] == {"risk_off_below": 40, "trend_at_least": 55}
    assert [row["horizon_sessions"] for row in result["results"]] == [3, 5, 10]
    assert result["results"][0]["total_samples"] == 28
    assert sum(row["samples"] for row in result["results"][0]["by_market_state"]) == 28
