from pathlib import Path

from app.database import Database
from app.factor_validation import (
    _average_ranks, _correlation, _weight_sensitivity, factor_validation_report,
)


def test_average_ranks_handle_ties():
    assert _average_ranks([10, 20, 20, 40]) == [1, 2.5, 2.5, 4]


def test_rank_correlation_detects_monotonic_relationship():
    assert round(_correlation(_average_ranks([1, 2, 3]), _average_ranks([2, 4, 8])), 6) == 1


def test_factor_report_refuses_to_infer_from_missing_samples(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()

    report = factor_validation_report(database)

    assert report["matured_signals"] == 0
    assert report["testable_factors"] == 0
    assert all(row["status"] == "insufficient_sample" for row in report["factors"])
    assert all(row["status"] == "insufficient_sample"
               for row in report["weight_sensitivity"])


def test_weight_sensitivity_keeps_baseline_and_one_scenario_per_factor():
    rows = []
    for index in range(25):
        score = float(index * 4)
        rows.append({
            "return_percent": float(index),
            "factors": {
                "business_quality_score": score,
                "cashflow_quality_score": score,
                "durability_score": score,
                "value_score": score,
                "risk_resilience_score": score,
                "growth_quality_score": score,
                "market_score": score,
            },
        })

    report = _weight_sensitivity(rows, "evidence_based", minimum_sample=20)

    assert report[0]["scenario"] == "baseline"
    assert len(report) == 8
    assert all(row["status"] == "testable" for row in report)
    assert report[0]["rank_ic"] == 1


def test_performance_factor_endpoint_accepts_browser_query_string():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/performance/factors?profile=evidence_based&horizon=20")

    assert response.status_code == 200
    assert response.json()["horizon"] == 20
