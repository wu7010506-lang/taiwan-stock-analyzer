from app.financials import _decimal, analyze_financials


def test_financial_decimal_missing_value():
    assert _decimal("") is None
    assert float(_decimal("1,234.5")) == 1234.5


def test_financial_analysis_for_first_quarter():
    rows = [{
        "symbol": "2330", "fiscal_year": 2026, "fiscal_quarter": 1,
        "report_type": "ci", "revenue": 1000.0, "gross_profit": 600.0,
        "operating_income": 400.0, "net_income": 300.0, "eps": 10.0,
        "current_assets": 800.0, "total_assets": 2000.0,
        "current_liabilities": 400.0, "total_liabilities": 700.0,
        "equity": 1300.0, "book_value_per_share": 50.0,
    }]
    result = analyze_financials(rows)
    assert result["gross_margin_percent"] == 60
    assert result["operating_margin_percent"] == 40
    assert result["debt_ratio_percent"] == 35
    assert result["current_ratio_percent"] == 200
    assert result["annualized_roe_percent"] > 90
    assert result["profitability_status"] == "本期獲利"
