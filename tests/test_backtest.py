from datetime import date

from app.backtest import _available_on, _monthly_dates


def test_backtest_applies_conservative_reporting_lag():
    assert _available_on({"statement_date": "2025-03-31", "fiscal_quarter": 1}) == date(2025, 5, 15)
    assert _available_on({"statement_date": "2025-12-31", "fiscal_quarter": 4}) == date(2026, 3, 31)


def test_backtest_uses_last_trading_day_of_each_month():
    dates = ["2025-01-02", "2025-01-24", "2025-02-03", "2025-02-27"]
    assert _monthly_dates(dates, None, None) == ["2025-01-24", "2025-02-27"]
