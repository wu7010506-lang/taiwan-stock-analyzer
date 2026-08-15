from datetime import date, timedelta

from app.technical_indicators import calculate_technical_indicators


def test_indicators_mark_insufficient_warmup_as_unavailable():
    rows = [{"trade_date": "2026-01-01", "open": 10, "high": 11, "low": 9,
             "close": 10, "volume": 1000} for _ in range(10)]
    result = calculate_technical_indicators(rows)
    assert result["indicators"]["sma_20"] is None
    assert result["availability"]["trend"] is False


def test_indicators_accept_empty_history_as_unavailable():
    result = calculate_technical_indicators([])
    assert result["as_of"] is None
    assert result["indicators"]["sma_20"] is None


def test_indicators_are_calculated_only_from_supplied_history():
    rows = []
    for index in range(80):
        close = 100 + index
        rows.append({"trade_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                     "open": close - 1, "high": close + 2, "low": close - 2,
                     "close": close, "volume": 1000 + index})
    result = calculate_technical_indicators(rows)
    assert result["as_of"] == rows[-1]["trade_date"]
    assert all(result["availability"][key] for key in (
        "trend", "momentum", "volatility", "volume", "trend_strength", "money_flow"
    ))
    assert result["indicators"]["sma_20"] == 169.5
    assert result["indicators"]["sma_5"] == 177.0
    assert result["indicators"]["sma_10"] == 174.5
    assert result["indicators"]["return_5d_percent"] is not None
    assert result["indicators"]["return_10d_percent"] is not None
    assert result["indicators"]["volume_ratio_5"] is not None
    assert result["indicators"]["macd_histogram_change"] is not None
    assert result["indicators"]["rsi_14"] == 100.0
    assert result["engine"] in {"python", "talib"}
    assert result["indicators"]["breakout_20d"] is True
    assert result["indicators"]["volume_confirmation_20d"] is False
    assert result["indicators"]["trend_confirmation"] is True
    assert result["indicators"]["natr_14"] is not None
    assert result["indicators"]["keltner_upper_20"] is not None
    assert result["indicators"]["adx_14"] is not None
    assert result["indicators"]["mfi_14"] is not None
