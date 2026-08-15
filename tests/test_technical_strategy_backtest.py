from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.technical_strategy_backtest import (
    _same_exposure_index_benchmark, bollinger_rsi_mean_reversion_backtest,
    breakout_atr_backtest, ema_adx_atr_backtest,
)


def test_breakout_backtest_uses_next_session_entry_and_costs(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "Test", "TWSE", None)])
    rows = []
    for index in range(90):
        close = 100 + index * .1
        volume = 10_000
        if index == 65:
            close, volume = 120, 20_000
        if index == 66:
            close = 121
        if index == 67:
            close = 126
        rows.append(DailyPrice("1000", "TWSE", date(2026, 1, 1) + timedelta(days=index),
                               Decimal(str(close)), Decimal(str(close + 1)),
                               Decimal(str(close - 1)), Decimal(str(close)), volume))
    database.upsert_prices(rows)

    result = breakout_atr_backtest(database, min_turnover=1,
                                   out_of_sample_start=rows[66].trade_date.isoformat())

    assert result["signals"] >= 1
    assert result["trades"] >= 1
    assert "diagnostics" in result
    assert result["diagnostics"]["by_exit_reason"]
    assert result["outcomes"][0]["breakout_strength_percent"] is not None
    assert result["outcomes"][0]["relative_volume"] is not None
    assert result["outcomes"][0]["entry_date"] == rows[66].trade_date.isoformat()
    assert result["outcomes"][0]["net_return_percent"] is not None
    assert result["portfolio_simulation"]["initial_capital"] == 100
    assert result["portfolio_simulation"]["constraints"]["max_total_exposure_percent"] == 80
    assert result["formal_recommendation_allowed"] is False
    assert result["out_of_sample"]["benchmark_status"] == "insufficient_index_coverage"
    assert len(result["audit_records"]) == result["trades"]
    bounded = breakout_atr_backtest(database, min_turnover=1,
                                    end_date=rows[67].trade_date.isoformat())
    assert all(row["exit_date"] <= rows[67].trade_date.isoformat()
               for row in bounded["outcomes"])
    assert bounded["portfolio_simulation"]["unclosed_positions"] == 0


def test_technical_breakout_endpoint_exposes_cost_and_risk_parameters():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    names = {item["name"] for item in schema["paths"]["/performance/technical-breakout-backtest"]["get"]["parameters"]}
    assert {"lookback", "volume_multiple", "min_breakout_percent", "stop_atr_multiple", "reward_risk", "slippage_bps", "max_total_exposure_percent", "industry_limit_percent", "out_of_sample_start"} <= names


def test_ema_adx_strategy_reports_a_fixed_out_of_sample_split(tmp_path: Path):
    database = Database(tmp_path / "ema.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "Test", "TWSE", None)])
    rows = []
    for index in range(270):
        close = 200 - index * .3 if index < 120 else 164 + (index - 120) * .8
        rows.append(DailyPrice("1000", "TWSE", date(2025, 1, 1) + timedelta(days=index),
                               Decimal(str(close)), Decimal(str(close + 2)),
                               Decimal(str(close - 2)), Decimal(str(close)), 1_000_000))
    database.upsert_prices(rows)

    result = ema_adx_atr_backtest(database, min_turnover=1,
                                  out_of_sample_start=rows[230].trade_date.isoformat())

    assert result["formal_recommendation_allowed"] is False
    assert result["parameters"]["out_of_sample_start"] == rows[230].trade_date.isoformat()
    assert result["out_of_sample"]["start_date"] == rows[230].trade_date.isoformat()
    assert "portfolio_simulation" in result["out_of_sample"]
    assert result["out_of_sample"]["benchmark_status"] == "insufficient_index_coverage"
    assert len(result["audit_records"]) == result["trades"]


def test_same_exposure_index_benchmark_uses_identical_trade_windows_and_costs(tmp_path: Path):
    database = Database(tmp_path / "benchmark.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany("INSERT INTO market_index_snapshots(trade_date,close) VALUES(?,?)", [
            ("2026-01-02", 100), ("2026-01-10", 110),
        ])
    result = _same_exposure_index_benchmark(
        database, [{"symbol": "1000", "industry": "tech", "entry_date": "2026-01-02",
                    "exit_date": "2026-01-10", "net_return_percent": 12}],
        commission_bps=0, sell_tax_bps=0, slippage_bps=0,
        constraints={"max_total_exposure_percent": 80, "single_stock_limit_percent": 80,
                     "industry_limit_percent": 80},
    )
    assert result["status"] == "available_close_to_close_proxy"
    assert result["coverage_percent"] == 100
    assert result["benchmark_total_return_percent"] == 8
    assert result["excess_return_percent"] == 1.6


def test_bollinger_rsi_strategy_is_fixed_research_only_with_pit_audit(tmp_path: Path):
    database = Database(tmp_path / "bollinger.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "Test", "TWSE", None)])
    rows = []
    for index in range(80):
        close = 100.0 if index < 40 else (72.0 if index == 40 else 74.0 + (index - 41) * .7)
        rows.append(DailyPrice("1000", "TWSE", date(2026, 1, 1) + timedelta(days=index),
                               Decimal(str(close)), Decimal(str(close + 2)),
                               Decimal(str(close - 2)), Decimal(str(close)), 1_000_000))
    database.upsert_prices(rows)

    result = bollinger_rsi_mean_reversion_backtest(
        database, min_turnover=1, out_of_sample_start=rows[40].trade_date.isoformat())

    assert result["formal_recommendation_allowed"] is False
    assert result["parameters"]["rsi_entry"] == 30
    assert result["out_of_sample"]["start_date"] == rows[40].trade_date.isoformat()
    assert all(row["execution_date"] > row["decision_date"] for row in result["audit_records"])


def test_ema_adx_experiment_endpoint_is_explicitly_research_only():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    assert "/research/experiments/ema-adx" in schema["paths"]
    assert "/research/experiments/technical-breakout" in schema["paths"]
