from datetime import date, timedelta
from pathlib import Path

from decimal import Decimal

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.paper_strategy import (_candidate_definitions, _queue_rebalance_orders,
                                _queue_technical_breakout_orders, _risk_metrics,
                                paper_strategy_summary, run_paper_strategy_valuation)


def test_locked_paper_candidates_are_created_without_touching_user_watchlist(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()

    result = run_paper_strategy_valuation(database, date(2026, 7, 30))
    summary = paper_strategy_summary(database)

    assert result["formal_recommendation_allowed"] is False
    assert {row["strategy_key"] for row in result["summaries"]} == {"paper_baseline", "paper_cashflow_tilt", "paper_technical_breakout_atr", "paper_short_term_breakout_10d"}
    assert all(row["nav"] == 100 for row in result["summaries"])
    assert all(row["status"] == "locked_research_candidate" for row in summary["candidates"])
    assert all(row["evidence_status"] == "insufficient_forward_sample" for row in summary["candidates"])
    assert database.list_watchlist() == []


def test_technical_paper_candidate_is_locked_and_has_its_own_execution_contract(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    run_paper_strategy_valuation(database, date(2026, 7, 30))

    candidate = next(row for row in paper_strategy_summary(database)["candidates"]
                     if row["strategy_key"] == "paper_technical_breakout_atr")
    assert candidate["status"] == "locked_research_candidate"
    assert candidate["evidence_status"] == "insufficient_forward_sample"
    assert candidate["promotion_policy"]["automatic_promotion"] is False


def test_technical_paper_breakout_queues_only_next_open_order_with_signal_metadata(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "Test", "TWSE", "tech")])
    rows = []
    for index in range(70):
        close, volume = 100 + index * .1, 10_000
        if index == 65:
            close, volume = 120, 20_000
        rows.append(DailyPrice("1000", "TWSE", date(2026, 1, 1) + timedelta(days=index),
                               Decimal(str(close)), Decimal(str(close + 1)),
                               Decimal(str(close - 1)), Decimal(str(close)), volume))
    database.upsert_prices(rows)
    run_paper_strategy_valuation(database, rows[64].trade_date)
    definition = next(row for row in _candidate_definitions()
                      if row["strategy_key"] == "paper_technical_breakout_atr")

    queued = _queue_technical_breakout_orders(database, definition, rows[65].trade_date.isoformat(),
                                               rows[65].trade_date.isoformat(), {"decision_date": rows[65].trade_date.isoformat()})
    orders = database.list_paper_orders("paper_technical_breakout_atr", "pending")

    assert queued == 1
    assert orders[0]["side"] == "buy"
    assert orders[0]["signal_date"] == rows[65].trade_date.isoformat()
    assert "atr" in orders[0]["data_version_json"]
    run_paper_strategy_valuation(database, rows[66].trade_date)
    executed = database.list_paper_orders("paper_technical_breakout_atr")[0]
    positions = database.list_paper_positions("paper_technical_breakout_atr")
    assert executed["execution_date"] == rows[66].trade_date.isoformat()
    assert executed["status"] == "executed"
    assert len(positions) == 1
    database.upsert_prices([DailyPrice("1000", "TWSE", rows[67].trade_date,
                                        Decimal("95"), Decimal("96"), Decimal("80"), Decimal("90"), 10_000)])
    run_paper_strategy_valuation(database, rows[67].trade_date)
    sells = [row for row in database.list_paper_orders("paper_technical_breakout_atr", "pending")
             if row["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["signal_date"] == rows[67].trade_date.isoformat()
    assert "atr_stop_observed_after_close" in sells[0]["data_version_json"]


def test_short_term_paper_breakout_requires_the_fundamental_safety_gate(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "Test", "TWSE", "tech")])
    rows = []
    for index in range(70):
        close, volume = (120, 20_000) if index == 65 else (100 + index * .1, 10_000)
        rows.append(DailyPrice("1000", "TWSE", date(2026, 1, 1) + timedelta(days=index),
                               Decimal(str(close)), Decimal(str(close + 1)),
                               Decimal(str(close - 1)), Decimal(str(close)), volume))
    database.upsert_prices(rows)
    definition = next(row for row in _candidate_definitions()
                      if row["strategy_key"] == "paper_short_term_breakout_10d")

    queued = _queue_technical_breakout_orders(
        database, definition, rows[65].trade_date.isoformat(), rows[65].trade_date.isoformat(), {}
    )

    assert queued == 0
    assert database.list_paper_orders("paper_short_term_breakout_10d", "pending") == []


def test_paper_candidates_require_human_review_and_future_sample(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    run_paper_strategy_valuation(database, date(2026, 7, 30))

    policy = paper_strategy_summary(database)["candidates"][0]["promotion_policy"]

    assert policy["minimum_out_of_sample_months"] == 12
    assert policy["automatic_promotion"] is False


def test_paper_orders_sell_at_next_open_and_record_costs(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("1000", "Test", "TWSE", None)])
    database.upsert_prices([DailyPrice("1000", "TWSE", date(2026, 7, 30),
                                        Decimal("110"), Decimal("111"), Decimal("109"), Decimal("110"), 1000)])
    run_paper_strategy_valuation(database, date(2026, 7, 29))
    database.upsert_paper_position("paper_baseline", "1000", "TWSE", 1, 100, "2026-07-01")
    database.add_paper_order({"strategy_key": "paper_baseline", "signal_date": "2026-07-29",
                              "symbol": "1000", "market": "TWSE", "side": "sell",
                              "target_weight_percent": 0, "data_version_json": "{}"})

    run_paper_strategy_valuation(database, date(2026, 7, 30))

    order = [row for row in database.list_paper_orders("paper_baseline") if row["side"] == "sell"][0]
    assert order["status"] == "executed"
    assert order["execution_price"] == 110
    assert order["costs"] > 0
    assert not database.list_paper_positions("paper_baseline")


def test_governance_rejects_mature_candidate_that_lags_benchmark(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    run_paper_strategy_valuation(database, date(2026, 1, 1))
    dates = [f"2026-{month:02d}-01" for month in range(2, 13)] + ["2027-01-01"]
    for valuation_date in dates:
        database.save_paper_valuation({"strategy_key": "paper_baseline", "valuation_date": valuation_date,
                                       "cash": 90, "holdings_value": 5, "nav": 95, "benchmark_nav": 105,
                                       "benchmark_close": 100, "transaction_costs": 0, "data_version_json": "{}"})

    candidate = next(row for row in paper_strategy_summary(database)["candidates"] if row["strategy_key"] == "paper_baseline")

    assert candidate["evidence_status"] == "rejected_underperforming"


def test_paper_metrics_use_fixed_initial_capital_when_same_day_is_revalued():
    metrics = _risk_metrics([{"nav": 101.5, "benchmark_nav": 99.8}])

    assert metrics["return_percent"] == 1.5
    assert metrics["benchmark_return_percent"] == -0.2
    assert metrics["excess_return_percent"] == 1.7


def test_monthly_rebalance_queues_sell_orders_before_replacing_basket(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    run_paper_strategy_valuation(database, date(2026, 7, 30))
    database.upsert_paper_position("paper_baseline", "1000", "TWSE", 1, 100, "2026-07-01")
    definition = next(row for row in _candidate_definitions() if row["strategy_key"] == "paper_baseline")

    queued = _queue_rebalance_orders(database, definition, "2026-08-31", {"decision_date": "2026-08-31"})

    orders = database.list_paper_orders("paper_baseline", "pending")
    assert queued >= 1
    assert orders[-1]["side"] == "sell"
