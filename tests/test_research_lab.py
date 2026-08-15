from datetime import date, timedelta
from pathlib import Path

from app.database import Database
from app.research_lab import (
    breakout_walk_forward_study, factor_ablation_study, technical_execution_assumptions, technical_parameter_study,
    technical_research_governance,
)


def test_research_lab_is_explicitly_isolated_and_never_recommends(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    result = technical_parameter_study(database)

    assert result["isolated"] is True
    assert result["formal_recommendation_allowed"] is False
    assert result["ai_decisioning_enabled"] is False
    assert len(result["results"]) == 3
    assert result["test_family"]["selection_prohibited"] is True
    assert result["out_of_sample_start"] == "2026-01-01"
    assert all("out_of_sample_excess_return_percent" in row for row in result["results"])
    assert "not an intraday" in result["drawdown_disclosure"]
    assert "audit_records" in result


def test_factor_ablation_has_fixed_research_only_configurations(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()

    result = factor_ablation_study(database)

    assert result["isolated"] is True
    assert result["formal_recommendation_allowed"] is False
    assert [row["name"] for row in result["results"]] == ["baseline", "cashflow_tilt", "value_safety"]
    assert all(sum(row["weights"].values()) == 100 for row in result["results"])


def test_technical_governance_keeps_unvalidated_rules_out_of_live_decisions():
    result = technical_research_governance()

    assert result["formal_recommendation_allowed"] is False
    assert any(row["status"].startswith("未實作") for row in result["rules"])
    assert any(row["name"] == "布林20＋RSI14 均值回歸" and row["decision_use"].endswith("尚未接入今日決策")
               for row in result["rules"])
    assert any("樣本外" in item for item in result["promotion_requirements"])
    assert all(row["live_decision"] == "blocked" for row in result["evidence_matrix"])


def test_execution_contract_discloses_costs_and_incomplete_data_handling():
    result = technical_execution_assumptions()

    assert result["formal_recommendation_allowed"] is False
    details = " ".join(row["detail"] for row in result["assumptions"])
    assert "14.25 bps" in details
    assert "下市" in details


def test_breakout_walk_forward_uses_disjoint_frozen_folds(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany("INSERT INTO market_index_snapshots(trade_date,close) VALUES(?,?)", [
            ((date(2024, 1, 1) + timedelta(days=index)).isoformat(), 100 + index)
            for index in range(380)
        ])
    result = breakout_walk_forward_study(database)

    assert result["formal_recommendation_allowed"] is False
    assert result["parameter_refit_allowed"] is False
    assert len(result["folds"]) == 3
    assert all(row["embargo_sessions_after_fold"] == 5 for row in result["folds"])
