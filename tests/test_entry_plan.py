from app.entry_plan import build_entry_plan, build_investment_checklist


def _prices(count: int = 30) -> list[dict]:
    return [
        {"close": 100 + index, "high": 101 + index, "low": 99 + index,
         "volume": 10_000 + index * 100}
        for index in range(count)
    ]


def test_entry_plan_sizes_position_from_risk_budget_and_exposes_limits():
    result = build_entry_plan(
        _prices(), {"action": "buy"}, {"max_new_allocation_percent": 5}
    )

    assert result["status"] == "ready_for_review"
    assert result["actionable"] is True
    assert result["invalidation_price"] < result["current_price"]
    assert 0 < result["suggested_initial_position_percent"] <= 5
    assert result["risk_reward_ratio"] == 2.0


def test_investment_checklist_keeps_manual_research_visible():
    plan = build_entry_plan(_prices(), {"action": "buy"}, {"max_new_allocation_percent": 5})
    checklist = build_investment_checklist({
        "eligibility": {"formal_recommendation_allowed": True},
        "company_quality": {"score": 80}, "valuation_score": 65,
        "crowding_risk": "low",
    }, plan)

    assert checklist["passed"] == 5
    assert checklist["manual_research_required"]
