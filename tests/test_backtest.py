from datetime import date

from app.backtest import (
    _available_on,
    _cash_dividend_return_percent,
    _corporate_action_total_return,
    _monthly_dates,
    _stock_dividend_share_ratio,
)


def test_backtest_applies_conservative_reporting_lag():
    assert _available_on({"statement_date": "2025-03-31", "fiscal_quarter": 1}) == date(2025, 5, 15)
    assert _available_on({"statement_date": "2025-12-31", "fiscal_quarter": 4}) == date(2026, 3, 31)


def test_backtest_uses_last_trading_day_of_each_month():
    dates = ["2025-01-02", "2025-01-24", "2025-02-03", "2025-02-27"]
    assert _monthly_dates(dates, None, None) == ["2025-01-24", "2025-02-27"]


def test_backtest_includes_only_cash_dividends_paid_while_held():
    dividends = [
        {"ex_date": "2025-01-02", "cash_dividend": 5},
        {"ex_date": "2025-01-15", "cash_dividend": 3},
        {"ex_date": "2025-02-01", "cash_dividend": 4},
    ]

    result = _cash_dividend_return_percent(dividends, "2025-01-02", "2025-01-31", 100)

    assert result == 3


def test_stock_dividend_units_are_normalized_by_source():
    assert _stock_dividend_share_ratio({"stock_dividend_ratio": 2, "source": "FinMind / MOPS"}) == .2
    assert _stock_dividend_share_ratio({"stock_dividend_ratio": .2, "source": "TPEx"}) == .2
    assert _stock_dividend_share_ratio({"stock_dividend_ratio": 20, "source": "TWSE"}) == .2


def test_total_return_values_cash_and_stock_dividends():
    events = [{"ex_date": "2025-01-15", "cash_dividend": 2,
               "stock_dividend_ratio": 2, "source": "FinMind / MOPS"}]

    result = _corporate_action_total_return(events, "2025-01-02", "2025-01-31", 100, 90)

    assert round(result["cash"], 4) == 2
    assert round(result["stock"], 4) == 18
    assert round(result["total"], 4) == 10
    assert result["share_multiplier"] == 1.2
