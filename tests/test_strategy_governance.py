from pathlib import Path

from app.database import Database
from app.strategy_governance import lookahead_audit, record_strategy_experiment


def test_lookahead_audit_rejects_future_available_data():
    audit = lookahead_audit([{"symbol": "1000", "decision_date": "2026-01-10", "available_at": "2026-01-11"}])
    assert audit["status"] == "failed"
    assert audit["violations"][0]["reason"] == "future_data_used"


def test_lookahead_audit_rejects_same_session_execution_after_close_signal():
    audit = lookahead_audit([{"symbol": "1000", "decision_date": "2026-01-10",
                              "available_at": "2026-01-10", "execution_date": "2026-01-10"}])
    assert audit["status"] == "failed"
    assert audit["violations"][0]["reason"] == "same_or_prior_session_execution"


def test_strategy_experiment_persists_auditable_candidate(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    result = {"out_of_sample": {"periods": 6},
              "out_of_sample_allocation_matched_benchmark": {"excess_return_percent": 1.2}}
    saved = record_strategy_experiment(
        database, strategy_key="market", strategy_version="v1", parameters={"top_n": 10},
        result=result, audit_records=[{"symbol": "1000", "decision_date": "2026-01-10", "available_at": "2026-01-10"}],
    )
    assert saved["status"] == "candidate"
    assert database.list_strategy_experiment_runs()[0]["id"] == saved["id"]


def test_technical_experiment_needs_oos_trades_and_a_matched_benchmark(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    saved = record_strategy_experiment(
        database, strategy_key="technical", strategy_version="v1", parameters={},
        result={"mode": "technical_ema_adx_atr_backtest", "out_of_sample": {"trades": 20},
                "out_of_sample_allocation_matched_benchmark": {}},
        audit_records=[{"symbol": "1000", "decision_date": "2026-01-10", "available_at": "2026-01-10"}],
    )
    assert saved["status"] == "insufficient_benchmark"


def test_walk_forward_rejects_a_strategy_with_any_nonpositive_forward_fold(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    saved = record_strategy_experiment(
        database, strategy_key="walk", strategy_version="v1", parameters={},
        result={"mode": "technical_breakout_walk_forward", "folds": [
            {"oos_excess_return_percent": 1}, {"oos_excess_return_percent": -1},
            {"oos_excess_return_percent": 2},
        ]}, audit_records=[{"symbol": "1000", "decision_date": "2026-01-10", "available_at": "2026-01-10"}],
    )
    assert saved["status"] == "rejected_inconsistent_walk_forward"


def test_parameter_family_cannot_be_promoted_from_any_single_configuration(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    saved = record_strategy_experiment(
        database, strategy_key="parameters", strategy_version="v1", parameters={},
        result={"research_type": "technical_parameter_study", "out_of_sample": {"periods": 99}},
        audit_records=[{"symbol": "1000", "decision_date": "2026-01-10", "available_at": "2026-01-10"}],
    )
    assert saved["status"] == "research_only_parameter_family"
