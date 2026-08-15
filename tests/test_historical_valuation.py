from app.historical_valuation import build_symbol_valuation_history


def test_historical_valuation_uses_reporting_lag_and_ttm():
    financials = []
    for year in (2024, 2025):
        for quarter in range(1, 5):
            financials.append({"fiscal_year": year, "fiscal_quarter": quarter,
                "statement_date": f"{year}-{quarter * 3:02d}-28",
                "eps": 2, "free_cash_flow": quarter * 100,
                "share_capital": 1000, "equity": 2000})
    prices = [
        {"trade_date": "2025-03-01", "close": 20},
        {"trade_date": "2025-04-01", "close": 20},
        {"trade_date": "2025-08-20", "close": 30},
        {"trade_date": "2026-04-01", "close": 40},
    ]
    result = build_symbol_valuation_history(financials, prices)
    # March can use the earlier balance sheet, but not the still-unreleased annual EPS.
    assert result["series"][0]["pe"] is None
    assert result["series"][1]["pe"] == 2.5
    assert result["observations"] == 4
    assert result["current_pe"] == 5
    assert result["current_pb"] == 2
    assert result["current_fcf_yield"] == 10
    assert result["history_reliable"] is False
    assert result["historical_value_score"] is None


def test_historical_valuation_prefers_reported_book_value_per_share():
    financials = [
        {"fiscal_year": 2025, "fiscal_quarter": quarter,
         "statement_date": f"2025-{quarter * 3:02d}-28", "eps": 2,
         "free_cash_flow": quarter * 100, "share_capital": 1_000,
         "equity": 2_000}
        for quarter in range(1, 5)
    ]
    # Some sources expose statement values in a different unit.  The supplied
    # per-share value is authoritative and must not be recalculated from it.
    financials[-1].update({"equity": 20, "book_value_per_share": 10})

    result = build_symbol_valuation_history(
        financials, [{"trade_date": "2026-04-01", "close": 20}]
    )

    assert result["current_pb"] == 2
