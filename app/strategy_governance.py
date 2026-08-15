from __future__ import annotations

import json
from datetime import datetime

from app.database import Database


def lookahead_audit(records: list[dict]) -> dict:
    """Verify that every signal field was available no later than its decision date."""
    violations = []
    for record in records:
        decision_date = record.get("decision_date")
        available_at = record.get("available_at")
        if not decision_date or not available_at:
            violations.append({"symbol": record.get("symbol"), "reason": "missing_availability_timestamp"})
        elif str(available_at) > str(decision_date):
            violations.append({"symbol": record.get("symbol"), "reason": "future_data_used",
                               "available_at": available_at, "decision_date": decision_date})
        elif record.get("execution_date") and str(record["execution_date"]) <= str(decision_date):
            violations.append({"symbol": record.get("symbol"), "reason": "same_or_prior_session_execution",
                               "execution_date": record["execution_date"], "decision_date": decision_date})
    return {"status": "passed" if not violations else "failed", "checked": len(records),
            "violations": violations}


def experiment_status(result: dict, audit: dict, minimum_periods: int = 6) -> str:
    oos = result.get("out_of_sample") or {}
    matched = result.get("out_of_sample_allocation_matched_benchmark") or {}
    if audit["status"] != "passed":
        return "rejected_lookahead"
    if result.get("research_type") == "technical_parameter_study":
        return "research_only_parameter_family"
    if result.get("mode") == "technical_breakout_walk_forward":
        folds = result.get("folds") or []
        excess = [row.get("oos_excess_return_percent") for row in folds]
        if len(folds) < 3 or any(value is None for value in excess):
            return "insufficient_walk_forward_evidence"
        if any(float(value) <= 0 for value in excess):
            return "rejected_inconsistent_walk_forward"
        return "candidate"
    # Technical trade studies do not yet have a same-exposure market benchmark.
    # Retain their evidence, but never promote them on raw return alone.
    if str(result.get("mode") or "").startswith("technical_"):
        if int(oos.get("trades") or 0) < 20:
            return "insufficient_out_of_sample"
        if matched.get("excess_return_percent") is None:
            return "insufficient_benchmark"
        return "candidate" if float(matched["excess_return_percent"]) > 0 else "rejected_underperforming"
    if int(oos.get("periods") or 0) < minimum_periods:
        return "insufficient_out_of_sample"
    if matched.get("excess_return_percent") is None:
        return "insufficient_benchmark"
    return "candidate" if float(matched["excess_return_percent"]) > 0 else "rejected_underperforming"


def record_strategy_experiment(database: Database, *, strategy_key: str, strategy_version: str,
                               parameters: dict, result: dict, audit_records: list[dict],
                               train_start: str | None = None, train_end: str | None = None,
                               out_of_sample_start: str | None = None,
                               out_of_sample_end: str | None = None) -> dict:
    audit = lookahead_audit(audit_records)
    status = experiment_status(result, audit)
    run_id = database.save_strategy_experiment_run(
        strategy_key, strategy_version, json.dumps(parameters, sort_keys=True),
        json.dumps(audit, ensure_ascii=False), json.dumps(result, ensure_ascii=False, default=str), status,
        train_start, train_end, out_of_sample_start, out_of_sample_end,
    )
    return {"id": run_id, "status": status, "lookahead_audit": audit,
            "recorded_at": datetime.now().isoformat(timespec="seconds")}


def experiment_history(database: Database, strategy_key: str | None = None, limit: int = 50) -> list[dict]:
    """Return persisted experiments with JSON decoded for the research UI/API."""
    rows = database.list_strategy_experiment_runs(strategy_key, limit)
    history = []
    for row in rows:
        history.append({**row,
                        "parameters": json.loads(row.pop("parameters_json")),
                        "lookahead_audit": json.loads(row.pop("lookahead_audit_json")),
                        "result": json.loads(row.pop("result_json"))})
    return history
