from app.valuation import _decimal, analyze_valuations


def test_valuation_decimal_handles_missing():
    assert _decimal("N/A") is None
    assert _decimal("-") is None
    assert float(_decimal("12.34")) == 12.34


def test_valuation_analysis_percentiles():
    rows = [
        {
            "symbol": "2330",
            "valuation_date": f"20260{index + 1}28",
            "pe_ratio": 10 + index,
            "pb_ratio": 2 + index / 10,
            "dividend_yield": 3 - index / 10,
            "financial_period": "115/1",
        }
        for index in range(6)
    ]
    result = analyze_valuations(rows)
    assert result["pe_ratio"] == 15
    assert result["pe_percentile"] == 100
    assert result["relative_valuation_band"] == "歷史相對高檔"
    assert result["observations"] == 6
