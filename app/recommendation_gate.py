from __future__ import annotations


def formal_recommendation_gate(quality_report: dict) -> dict:
    """Return the one shared decision for whether formal actions are allowed."""
    contracts = quality_report.get("contracts")
    # A compact legacy/failed-safe quality response may only contain a status.
    # Full reports always include contracts; keep the dashboard available while
    # still refusing any explicit failed contract.
    contracts_passed = (
        contracts.get("status") == "passed" if isinstance(contracts, dict)
        else quality_report.get("status") == "healthy"
    )
    terminal_jobs = int(quality_report.get("queues", {}).get("sync_jobs", {}).get("terminal_failed") or 0)
    allowed = contracts_passed and terminal_jobs == 0
    reasons = []
    if not contracts_passed:
        reasons.append("data_contract_not_met")
    if terminal_jobs:
        reasons.append("terminal_sync_jobs")
    return {
        "allowed": allowed,
        "data_quality_status": quality_report.get("status"),
        "failed_contracts": quality_report.get("contracts", {}).get("failed", 0),
        "terminal_sync_jobs": terminal_jobs,
        "reasons": reasons,
        "message": (
            "資料契約完整，清單可作為正式推薦候選。"
            if allowed else "資料契約或同步工作未完成；清單僅供研究觀察，不得視為正式推薦。"
        ),
    }


def apply_formal_recommendation_gate(result: dict, quality_report: dict) -> dict:
    """Attach the shared decision without silently deleting research output."""
    gate = formal_recommendation_gate(quality_report)
    result["formal_recommendation_gate"] = gate
    if not gate["allowed"]:
        for row in result.get("recommendations", []):
            row["formal_recommendation_allowed"] = False
            row.setdefault("risks", []).append("global_data_quality_gate")
    return result
