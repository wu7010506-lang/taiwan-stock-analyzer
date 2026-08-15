from app.portfolio_engine import construct_portfolio, portfolio_period_return, simulate_fixed_capital_trades


def test_portfolio_engine_enforces_single_industry_and_total_limits():
    result = construct_portfolio([
        {"symbol": "A", "industry": "semiconductor", "return_percent": 10},
        {"symbol": "B", "industry": "semiconductor", "return_percent": 5},
        {"symbol": "C", "industry": "financial", "return_percent": -2},
    ], max_total_exposure_percent=60, single_stock_limit_percent=30, industry_limit_percent=25)

    assert result["invested_percent"] == 45
    assert result["cash_percent"] == 55
    assert result["rejected"] == []
    assert {row["symbol"]: row["target_weight_percent"] for row in result["allocations"]}["B"] == 5


def test_portfolio_engine_applies_costs_to_invested_exposure_only():
    result = portfolio_period_return([
        {"target_weight_percent": 20, "return_percent": 10},
        {"target_weight_percent": 20, "return_percent": -5},
    ], commission_bps=10, sell_tax_bps=30, slippage_bps=5)

    assert result["gross_return_percent"] == 1
    assert result["cost_percent"] == 0.14
    assert result["net_return_percent"] == 0.86


def test_fixed_capital_simulation_keeps_cash_and_caps_overlapping_positions():
    result = simulate_fixed_capital_trades([
        {"symbol": "A", "industry": "tech", "entry_date": "2026-01-02", "exit_date": "2026-01-10", "net_return_percent": 10, "rank": 1},
        {"symbol": "B", "industry": "tech", "entry_date": "2026-01-03", "exit_date": "2026-01-11", "net_return_percent": 10, "rank": 1},
    ], max_total_exposure_percent=80, single_stock_limit_percent=50, industry_limit_percent=50)

    assert result["ending_capital"] == 105
    assert result["net_return_percent"] == 5
    assert result["equity_curve"][1]["invested"] == 50
    assert result["rejected_trades"][0]["symbol"] == "B"


def test_fixed_capital_simulation_settles_an_intraday_same_session_exit():
    result = simulate_fixed_capital_trades([
        {"symbol": "A", "industry": "tech", "entry_date": "2026-01-02",
         "exit_date": "2026-01-02", "net_return_percent": 10},
    ], max_total_exposure_percent=80, single_stock_limit_percent=80, industry_limit_percent=80)

    assert result["ending_capital"] == 108
    assert result["unclosed_positions"] == 0
    assert result["equity_curve"][0]["invested"] == 0
