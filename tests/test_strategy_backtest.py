from app.strategy_backtest import _attribution_report, _period_metrics


def test_period_metrics_keeps_out_of_sample_equity_separate_from_in_sample():
    in_sample = _period_metrics([
        {"strategy_return_percent": 10, "benchmark_return_percent": 5},
        {"strategy_return_percent": -10, "benchmark_return_percent": -5},
    ])
    out_of_sample = _period_metrics([
        {"strategy_return_percent": 20, "benchmark_return_percent": 10},
    ])

    assert in_sample["periods"] == 2
    assert round(in_sample["total_return_percent"], 2) == -1
    assert round(in_sample["benchmark_total_return_percent"], 2) == -0.25
    assert round(in_sample["max_drawdown_percent"], 2) == -10
    assert out_of_sample == {
        "periods": 1,
        "total_return_percent": 20,
        "benchmark_total_return_percent": 10,
        "excess_return_percent": 10,
        "max_drawdown_percent": 0,
        "monthly_volatility_percent": None,
    }


def test_period_metrics_reports_empty_partition_without_making_up_a_score():
    assert _period_metrics([]) == {
        "periods": 0,
        "total_return_percent": None,
        "benchmark_total_return_percent": None,
        "excess_return_percent": None,
        "max_drawdown_percent": None,
        "monthly_volatility_percent": None,
    }


def test_period_metrics_can_use_allocation_matched_benchmark():
    outcomes = [{"strategy_return_percent": 8, "benchmark_return_percent": 10,
                 "allocation_matched_benchmark_return_percent": 7}]

    result = _period_metrics(outcomes, "allocation_matched_benchmark_return_percent")

    assert result["benchmark_total_return_percent"] == 7
    assert result["excess_return_percent"] == 1


def test_attribution_uses_target_weighted_contribution_and_regime_benchmarks():
    report = _attribution_report([{
        "cash_percent": 60, "strategy_return_percent": 2,
        "allocation_matched_benchmark_return_percent": 1,
        "allocations": [{"symbol": "A", "industry": "tech", "target_weight_percent": 20,
                         "return_percent": 10, "factors": {"business_quality": 80}}],
    }, {
        "cash_percent": 20, "strategy_return_percent": -1,
        "allocation_matched_benchmark_return_percent": 0,
        "allocations": [{"symbol": "B", "industry": "finance", "target_weight_percent": 10,
                         "return_percent": -5, "factors": {"business_quality": 40}}],
    }])

    assert report["by_industry"][0]["label"] == "tech"
    assert report["by_industry"][0]["contribution_percent"] == 2
    assert {row["regime"] for row in report["by_market_regime"]} == {"defensive", "bullish"}
    assert report["factor_score_return_correlation"][0]["sample_size"] == 2


def test_strategy_backtest_endpoint_exposes_slippage_and_liquidity_parameters():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    parameters = schema["paths"]["/performance/strategy-backtest"]["get"]["parameters"]
    names = {item["name"] for item in parameters}
    assert {"slippage_bps", "min_turnover", "out_of_sample_start"} <= names


def test_vnext_walk_forward_endpoint_exposes_pit_and_cost_parameters():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    parameters = schema["paths"]["/performance/vnext-walk-forward"]["get"]["parameters"]
    names = {item["name"] for item in parameters}
    assert {"horizon", "commission_bps", "sell_tax_bps", "slippage_bps",
            "min_turnover", "embargo_sessions", "technical_timing"} <= names


def test_research_weights_are_kept_out_of_the_public_strategy_backtest_interface():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    names = {item["name"] for item in schema["paths"]["/performance/strategy-backtest"]["get"]["parameters"]}
    assert "research_weights" not in names
    assert "/research/factor-ablation" in schema["paths"]
