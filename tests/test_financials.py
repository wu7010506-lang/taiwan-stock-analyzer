from app.financials import _decimal, analyze_financials, normalize_financial_rows


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


def test_official_financial_snapshot_has_period_end_date_for_quality_contract():
    income = {
        "出表日期": "1150811", "公司代號": "2330", "年度": "115", "季別": "2", "營業收入": "1000",
        "營業毛利（毛損）淨額": "500", "營業利益（損失）": "300",
        "本期淨利（淨損）": "200", "基本每股盈餘（元）": "5",
    }
    balance = {"公司代號": "2330", "流動資產": "800", "資產總額": "2000",
               "流動負債": "400", "負債總額": "700", "權益總額": "1300"}

    row = normalize_financial_rows(income, balance, "ci", "TWSE")

    assert row["statement_date"] == "2026-06-30"
    assert row["published_date"] is None
    assert row["source_as_of_date"] == "2026-08-11"
    assert row["source"] == "TWSE official OpenAPI"
    assert row["monetary_unit"] == "TWD"
    assert float(row["revenue"]) == 1_000_000
    assert float(row["total_assets"]) == 2_000_000
    assert float(row["equity"]) == 1_300_000
    assert float(row["eps"]) == 5
