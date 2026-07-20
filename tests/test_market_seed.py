import json

from app.database import Database
from app.market_seed import load_market_seed


def test_market_seed_populates_fresh_database(tmp_path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({
        "instruments": [{"symbol": "2330", "name": "台積電", "market": "TWSE"}],
        "prices": [{"symbol": "2330", "market": "TWSE", "trade_date": "2026-07-17",
                    "open": 1000, "high": 1010, "low": 990, "close": 1005,
                    "volume": 10000, "turnover": 10050000, "transaction_count": 900}],
    }, ensure_ascii=False), encoding="utf-8")

    result = load_market_seed(database, seed)

    assert result == {"instruments": 1, "prices": 1}
    assert database.get_instrument("2330")["name"] == "台積電"
