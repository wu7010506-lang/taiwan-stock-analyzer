from __future__ import annotations


def apply_formal_recommendation_gate(result: dict, quality_report: dict) -> dict:
    """Attach a global data-contract decision without silently deleting research output."""
    contracts_passed = quality_report.get("contracts", {}).get("status") == "passed"
    terminal_jobs = int(quality_report.get("queues", {}).get("sync_jobs", {}).get("terminal_failed") or 0)
    allowed = contracts_passed and terminal_jobs == 0
    reasons = []
    if not contracts_passed:
        reasons.append("data_contract_not_met")
    if terminal_jobs:
        reasons.append("terminal_sync_jobs")
    result["formal_recommendation_gate"] = {
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
    if not allowed:
        for row in result.get("recommendations", []):
            row["formal_recommendation_allowed"] = False
            row.setdefault("risks", []).append("global_data_quality_gate")
    return result
