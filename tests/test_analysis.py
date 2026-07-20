import pytest

from app.analysis import analyze, ema, rsi, sma
from app.providers import _parse_date


def test_moving_averages():
    values = [1, 2, 3, 4, 5]
    assert sma(values, 3) == 4
    assert ema(values, 3) == pytest.approx(4)


def test_rsi_for_only_gains():
    assert rsi(list(range(1, 17)), 14) == 100


def test_analysis_returns_latest_metrics():
    rows = [
        {"symbol": "2330", "trade_date": f"2026-01-{index:02d}", "close": index,
         "volume": 1000}
        for index in range(1, 22)
    ]
    result = analyze(rows)
    assert result["symbol"] == "2330"
    assert result["close"] == 21
    assert result["sma_5"] == 19
    assert result["return_20d"] == 20
    assert result["all_time_high_close"] == 21
    assert result["all_time_high_date"] == "2026-01-21"
    assert result["from_all_time_high"] == 0


def test_analysis_calculates_distance_from_historical_high():
    rows = [
        {"symbol": "2330", "trade_date": f"2026-01-0{index}", "close": close,
         "volume": 1000}
        for index, close in enumerate([80, 100, 90], start=1)
    ]
    result = analyze(rows)
    assert result["all_time_high_close"] == 100
    assert result["all_time_high_date"] == "2026-01-02"
    assert result["from_all_time_high"] == pytest.approx(-0.1)


def test_parse_roc_compact_date():
    assert _parse_date("1150717").isoformat() == "2026-07-17"
