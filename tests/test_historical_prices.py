from app.historical_prices import normalize_finmind_prices


def test_normalizes_finmind_prices():
    rows = normalize_finmind_prices([{"date": "2026-07-22", "stock_id": "2330",
        "Trading_Volume": 1000, "Trading_money": 1500000, "open": 1490,
        "max": 1510, "min": 1480, "close": 1500, "Trading_turnover": 123}], "TWSE")
    assert len(rows) == 1
    assert rows[0].symbol == "2330"
    assert float(rows[0].close) == 1500
    assert rows[0].volume == 1000
