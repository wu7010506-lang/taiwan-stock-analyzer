from app.strategy_backtest import _period_metrics


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


def test_strategy_backtest_endpoint_exposes_slippage_and_liquidity_parameters():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    parameters = schema["paths"]["/performance/strategy-backtest"]["get"]["parameters"]
    names = {item["name"] for item in parameters}
    assert {"slippage_bps", "min_turnover", "out_of_sample_start"} <= names
