from app.recommendation_gate import apply_formal_recommendation_gate


def test_failed_contract_keeps_research_rows_but_blocks_formal_recommendation():
    result = {"recommendations": [{"symbol": "2330", "risks": []}]}
    report = {"status": "warning", "contracts": {"status": "failed", "failed": 1},
              "queues": {"sync_jobs": {"terminal_failed": 0}}}

    apply_formal_recommendation_gate(result, report)

    assert result["formal_recommendation_gate"]["allowed"] is False
    assert result["recommendations"][0]["formal_recommendation_allowed"] is False
    assert "global_data_quality_gate" in result["recommendations"][0]["risks"]


def test_complete_contract_allows_formal_recommendation():
    result = {"recommendations": []}
    report = {"status": "healthy", "contracts": {"status": "passed", "failed": 0},
              "queues": {"sync_jobs": {"terminal_failed": 0}}}

    apply_formal_recommendation_gate(result, report)

    assert result["formal_recommendation_gate"]["allowed"] is True
