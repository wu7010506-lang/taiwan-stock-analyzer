from app.database import Database
from app.screening import ScreenerFilters, _roc_month, _sync_valuations, screening_csv


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


def test_daily_valuation_sync_preserves_official_financial_period(
    tmp_path, monkeypatch
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()

    def fake_fetch_rows(client, url):
        if "BWIBBU_ALL" in url:
            return [{
                "Date": "1150813",
                "Code": "2344",
                "PEratio": "19.51",
                "PBratio": "4.83",
                "DividendYield": "0.28",
            }]
        return []

    def fake_snapshot(client, market, target):
        assert market == "TWSE"
        assert target.isoformat() == "2026-08-13"
        return {
            "2344": {
                "symbol": "2344",
                "market": "TWSE",
                "valuation_date": "20260813",
                "close_price": 177,
                "pe_ratio": 19.51,
                "pb_ratio": 4.83,
                "dividend_yield": 0.28,
                "financial_period": "115/2",
            }
        }

    monkeypatch.setattr("app.screening._fetch_rows", fake_fetch_rows)
    monkeypatch.setattr("app.screening.fetch_valuation_snapshot", fake_snapshot)

    assert _sync_valuations(database, object()) == 1
    row = database.get_valuations("2344", 1)[0]
    assert row["close_price"] == 177
    assert row["financial_period"] == "115/2"
