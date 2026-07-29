from datetime import date, timedelta

from app.technical_indicators import calculate_technical_indicators


def test_indicators_mark_insufficient_warmup_as_unavailable():
    rows = [{"trade_date": "2026-01-01", "open": 10, "high": 11, "low": 9,
             "close": 10, "volume": 1000} for _ in range(10)]
    result = calculate_technical_indicators(rows)
    assert result["indicators"]["sma_20"] is None
    assert result["availability"]["trend"] is False


def test_indicators_are_calculated_only_from_supplied_history():
    rows = []
    for index in range(80):
        close = 100 + index
        rows.append({"trade_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                     "open": close - 1, "high": close + 2, "low": close - 2,
                     "close": close, "volume": 1000 + index})
    result = calculate_technical_indicators(rows)
    assert result["as_of"] == rows[-1]["trade_date"]
    assert result["availability"] == {"trend": True, "momentum": True,
                                       "volatility": True, "volume": True}
    assert result["indicators"]["sma_20"] == 169.5
    assert result["indicators"]["rsi_14"] == 100.0
