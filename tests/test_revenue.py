from decimal import Decimal

from app.database import Database
from app.domain import Instrument
from app.revenue import _RevenueTableParser, analyze_revenue, sync_revenue


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


def test_sync_revenue_uses_latest_official_bulk_row_when_monthly_html_misses(
    tmp_path, monkeypatch,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([
        Instrument("2637", "Wisdom Marine", "TWSE", "26")
    ])

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("app.revenue.httpx.Client", FakeClient)
    monkeypatch.setattr("app.revenue.fetch_revenue_month", lambda *args: None)
    monkeypatch.setattr(
        "app.revenue.fetch_latest_revenue",
        lambda *args: {
            "symbol": "2637", "market": "TWSE", "revenue_month": "2026-07",
            "revenue": Decimal("2097738"), "previous_month_revenue": None,
            "previous_year_revenue": None, "mom_percent": None,
            "yoy_percent": Decimal("56.215"), "cumulative_revenue": None,
            "previous_year_cumulative_revenue": None,
            "cumulative_yoy_percent": None,
        },
        raising=False,
    )

    result = sync_revenue(database, "2637", "2026-07", "2026-08")

    assert result["rows_written"] == 1
    assert database.get_monthly_revenues("2637", 1)[0]["revenue_month"] == "2026-07"
