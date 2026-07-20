from app.screening import ScreenerFilters, _roc_month, screening_csv


def test_roc_month_conversion():
    assert _roc_month("11506") == "2026-06"


def test_screener_filters_defaults():
    filters = ScreenerFilters()
    assert filters.limit == 100
    assert filters.sort_by == "completeness"
    assert filters.popular_only is True
    assert filters.ai_theme is False
    assert filters.defense_drone_theme is False
    assert filters.ic_design_theme is False


def test_screening_csv_has_bom_and_rows():
    row = {key: None for key in [
        "symbol", "name", "market", "industry", "close", "revenue_yoy",
        "gross_margin", "roe", "debt_ratio", "pe", "pb", "dividend_yield",
        "sma60", "rsi14", "completeness",
    ]}
    row.update({"symbol": "2330", "name": "台積電"})
    output = screening_csv([row])
    assert output.startswith("\ufeff")
    assert "2330" in output
