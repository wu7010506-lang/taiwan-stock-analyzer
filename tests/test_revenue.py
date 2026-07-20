from app.revenue import _RevenueTableParser, analyze_revenue


def test_revenue_html_parser():
    parser = _RevenueTableParser()
    parser.feed("<table><tr><td>2330</td><td>台積電</td><td>1,000</td></tr></table>")
    assert parser.rows == [["2330", "台積電", "1,000"]]


def test_revenue_analysis():
    rows = []
    for index in range(24):
        rows.append({
            "symbol": "2330",
            "revenue_month": f"2025-{index + 1:02d}" if index < 12 else f"2026-{index - 11:02d}",
            "revenue": 100 + index,
            "mom_percent": 1.0,
            "yoy_percent": 10.0,
        })
    result = analyze_revenue(rows)
    assert result["consecutive_positive_yoy_months"] == 24
    assert result["rolling_3m_yoy_percent"] > 0
    assert result["historical_percentile"] == 100
    assert result["is_record_high"] is True
