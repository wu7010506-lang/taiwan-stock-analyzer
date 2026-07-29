from pathlib import Path

from app.database import Database
from app.recommendation_watchlist import add_top_recommendations_to_watchlist


def test_adds_only_top_twenty_recommendations_without_removing_existing(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO instruments(symbol, market, name) VALUES (?, ?, ?)",
            [(f"{index:04d}", "TWSE", f"Stock {index}") for index in range(1, 23)]
            + [("9999", "TWSE", "Manual")],
        )
    database.add_to_watchlist("9999", "TWSE")
    result = {"recommendations": [
        {"symbol": f"{index:04d}", "market": "TWSE"} for index in range(1, 23)
    ]}

    sync = add_top_recommendations_to_watchlist(database, result)

    watched = {row["symbol"] for row in database.list_watchlist()}
    assert sync == {"considered": 20, "added": 20, "limit": 20}
    assert "0020" in watched
    assert "0021" not in watched
    assert "9999" in watched


def test_repeated_sync_is_idempotent(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO instruments(symbol, market, name) VALUES (?, ?, ?)",
            ("2330", "TWSE", "TSMC"),
        )
    result = {"recommendations": [{"symbol": "2330", "market": "TWSE"}]}

    add_top_recommendations_to_watchlist(database, result)
    second = add_top_recommendations_to_watchlist(database, result)

    assert second["added"] == 0
    assert len(database.list_watchlist()) == 1


def test_accepts_existing_research_recommendation_list(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO instruments(symbol, market, name) VALUES (?, ?, ?)",
            ("2454", "TWSE", "MediaTek"),
        )

    sync = add_top_recommendations_to_watchlist(
        database, [{"symbol": "2454", "market": "TWSE"}]
    )

    assert sync["added"] == 1
    assert database.is_watched("2454") is True
