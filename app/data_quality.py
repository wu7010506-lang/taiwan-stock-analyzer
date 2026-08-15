from __future__ import annotations

from datetime import date, datetime
import json

from app.database import Database
from app.source_policy import data_source_catalog
from app.analysis_sync import analysis_sync_plan
from app.vnext_eligibility import assess_vnext_data_eligibility


DATASET_LABELS = {
    "prices": "日價量",
    "revenues": "月營收",
    "valuations": "估值",
    "financials": "財報",
    "institutions": "法人買賣",
}

MAX_DATA_AGE_DAYS = {
    "prices": 7, "institutions": 7, "valuations": 14,
    "revenues": 62, "financials": 190,
}


def _contract_coverage(dataset: str, details: dict) -> tuple[float, str]:
    """Daily market data must cover the market's latest date, not merely a grace window."""
    if dataset == "institutions" and "exact_date_coverage_of_covered_percent" in details:
        return (
            float(details.get("exact_date_coverage_of_covered_percent") or 0),
            "exact_latest_date_recent_cohort",
        )
    if dataset in {"prices", "institutions"} and "exact_date_coverage_percent" in details:
        return float(details.get("exact_date_coverage_percent") or 0), "exact_latest_date"
    return float(details.get("coverage_percent") or 0), "freshness_window"


def _contract_coverage_counts(coverage_basis: str, details: dict) -> tuple[int, int]:
    """Use the same numerator and denominator as the reported contract percentage."""
    if coverage_basis == "exact_latest_date_recent_cohort":
        return (
            int(details.get("exact_date_stocks") or 0),
            int(details.get("covered_stocks") or 0),
        )
    if coverage_basis == "exact_latest_date":
        return (
            int(details.get("exact_date_stocks") or 0),
            int(details.get("total_stocks") or 0),
        )
    return (
        int(details.get("covered_stocks") or 0),
        int(details.get("total_stocks") or 0),
    )


def evaluate_data_contracts(markets: dict, as_of_date: date | None = None) -> dict:
    """Evaluate minimum, explainable prerequisites for formal model use."""
    as_of_date = as_of_date or date.today()
    checks = []
    for market, datasets in markets.items():
        for dataset, details in datasets.items():
            required_coverage = 90 if dataset == "institutions" else 95
            coverage, coverage_basis = _contract_coverage(dataset, details)
            latest_date = details.get("latest_date")
            max_age_days = MAX_DATA_AGE_DAYS.get(dataset, 7)
            try:
                age_days = (as_of_date - date.fromisoformat(str(latest_date)[:10])).days
            except (TypeError, ValueError):
                age_days = None
            passed = (coverage >= required_coverage and latest_date is not None
                      and age_days is not None and age_days <= max_age_days)
            checks.append({
                "market": market, "dataset": dataset,
                "label": f"{market} {DATASET_LABELS.get(dataset, dataset)}",
                "status": "passed" if passed else "failed",
                "required_coverage_percent": required_coverage,
                "actual_coverage_percent": coverage,
                "coverage_basis": coverage_basis,
                "latest_date": latest_date,
                "max_age_days": max_age_days,
                "actual_age_days": age_days,
                "reason": None if passed else (
                    "缺少最新資料日期" if latest_date is None else
                    f"覆蓋率 {coverage:.1f}% 低於 {required_coverage}%"
                    if coverage < required_coverage else
                    f"資料落後 {age_days} 日，超過 {max_age_days} 日"
                ),
            })
    failed = [check for check in checks if check["status"] == "failed"]
    return {
        "status": "passed" if not failed else "failed",
        "passed": len(checks) - len(failed), "failed": len(failed),
        "checks": checks,
        "policy": "未通過的資料集不得用空值取代後產生正式推薦。",
    }


def _friendly_sync_error(error: str | None) -> str:
    text = str(error or "原因未記錄")
    if "quota" in text.lower():
        return "資料供應商公開 API 額度已用完，等待冷卻後自動續跑"
    return text


def vnext_history_coverage(database: Database, target_limit: int = 100,
                           as_of_date: date | None = None) -> dict:
    """Audit whether the prioritized universe can support strict vNext research.

    This is intentionally separate from daily freshness contracts: a stock can be
    current enough for a quote page but still unusable for a five-year PIT study.
    """
    as_of_date = as_of_date or date.today()
    rows = database.list_research_sync_universe(target_limit)
    status_counts = {"eligible": 0, "observation": 0, "insufficient_data": 0}
    missing_counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for row in rows:
        assessment = assess_vnext_data_eligibility(database, row["symbol"], as_of_date)
        status = assessment["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        for missing in assessment["missing"]:
            missing_counts[missing] = missing_counts.get(missing, 0) + 1
            examples.setdefault(missing, [])
            if len(examples[missing]) < 5:
                examples[missing].append(row["symbol"])
    total = len(rows)
    eligible_percent = round(status_counts["eligible"] / total * 100, 2) if total else 0.0
    return {"as_of_date": as_of_date.isoformat(), "checked": total,
            "eligible": status_counts["eligible"], "eligible_percent": eligible_percent,
            "observation": status_counts["observation"],
            "insufficient_data": status_counts["insufficient_data"],
            "missing_counts": missing_counts, "examples": examples,
            "status": "ready" if status_counts["eligible"] else "backfill_required"}


def build_data_quality_report(database: Database, target_limit: int = 100) -> dict:
    """Build one read-only report for freshness, coverage and failed sync jobs."""
    database.initialize()
    markets = database.get_market_data_freshness()
    quarantine_groups = [
        database.list_market_dataset_lagging_symbols(market, "prices", limit=20)
        for market in markets
    ]
    quarantine_groups = [row for row in quarantine_groups if row["lagging_count"]]
    contracts = evaluate_data_contracts(markets)
    latest_sync = database.get_latest_daily_sync_run()
    fundamental_queue = database.get_fundamental_sync_progress(None)
    price_queue = database.get_price_sync_progress(target_limit)
    sync_jobs = database.get_data_sync_job_progress()
    source_health = database.get_data_source_health()
    vnext_coverage = vnext_history_coverage(database, target_limit)
    universe_total = sum(
        next(iter(datasets.values())).get("total_stocks", 0) if datasets else 0
        for datasets in markets.values()
    )
    fundamental_queue["universe_total"] = universe_total
    fundamental_queue["full_market_initialized"] = (
        universe_total > 0 and fundamental_queue.get("total", 0) >= universe_total
    )
    issues: list[dict] = []
    resolved_since_sync: list[str] = []
    if vnext_coverage["status"] != "ready":
        missing = vnext_coverage["missing_counts"]
        issues.append({
            "severity": "warning", "code": "vnext_history_backfill_required",
            "dataset": "vnext_history", "title": "vNext 歷史研究資料尚未完成",
            "detail": (f"已檢查 {vnext_coverage['checked']} 檔，正式資格 0 檔；"
                       f"缺口：財報 {missing.get('financial_history', 0)}、"
                       f"價格 {missing.get('price_history', 0)}、"
                       f"新鮮度 {missing.get('freshness', 0)}。"),
            "action": "啟動歷史財報與價格回補；未完成前 vNext 歷史回測必須標示資料不足。",
        })

    for market, datasets in markets.items():
        for dataset, details in datasets.items():
            coverage, coverage_basis = _contract_coverage(dataset, details)
            healthy_threshold = 90 if dataset == "institutions" else 95
            if coverage >= healthy_threshold:
                continue
            critical_threshold = 60 if dataset == "institutions" else 70
            severity = "critical" if coverage < critical_threshold else "warning"
            is_financial_backfill = dataset == "financials" and (
                fundamental_queue.get("pending", 0) or fundamental_queue.get("running", 0)
            )
            covered_count, contract_total = _contract_coverage_counts(
                coverage_basis, details
            )
            issues.append({
                "severity": severity,
                "code": "coverage_backfill_in_progress" if is_financial_backfill else "low_coverage",
                "market": market,
                "dataset": dataset,
                "coverage_basis": coverage_basis,
                "title": f"{market} {DATASET_LABELS.get(dataset, dataset)}覆蓋率不足",
                "detail": (
                    f"最新一期 {details.get('latest_date') or '未知'} 僅覆蓋 "
                    f"{covered_count}/{contract_total} 檔"
                    + (f"；全市場佇列尚有 {fundamental_queue.get('remaining', 0)} 檔未完成"
                       if is_financial_backfill else "")
                ),
                "action": ("使用『補齊下一批完整財報』或等待每日收盤自動續跑；缺漏股票仍排除正式推薦。"
                           if is_financial_backfill else
                           "重新同步；若持續失敗，正式推薦應排除缺漏股票。"),
            })

    for queue_name, queue_label, queue in (
        ("fundamentals", "五年研究資料", fundamental_queue),
        ("prices", "三年歷史價格", price_queue),
    ):
        failed = int(queue.get("failed") or 0)
        if failed:
            issues.append({
                "severity": "warning",
                "code": "failed_jobs",
                "dataset": queue_name,
                "terminal_failed": int(queue.get("terminal_failed") or 0),
                "title": f"{queue_label}有 {failed} 檔同步失敗",
                "detail": "；".join(
                    f"{row.get('symbol')} {_friendly_sync_error(row.get('error'))}"
                    for row in (queue.get("failures") or [])[:5]
                ),
                "action": "稍後重試失敗批次，並保留錯誤原因供資料源替代判斷。",
            })

    oldest_backlog = fundamental_queue.get("oldest_pending_at")
    if oldest_backlog:
        try:
            backlog_days = (datetime.now() - datetime.fromisoformat(oldest_backlog)).total_seconds() / 86400
        except ValueError:
            backlog_days = 0
        if backlog_days > 7:
            issues.append({
                "severity": "warning", "code": "sync_backlog_sla",
                "dataset": "financials", "backlog_age_days": round(backlog_days, 1),
                "title": "同步待辦逾 7 天未完成",
                "detail": f"最早未完成的財報同步工作建立於 {oldest_backlog}，正式推薦會維持資料品質限制。",
                "action": "檢查資料來源、失敗原因與網路配額；修正後由每日同步依冷卻時間續跑。",
            })

    if sync_jobs.get("terminal_failed"):
        issues.append({
            "severity": "critical", "code": "terminal_sync_jobs",
            "title": f"有 {sync_jobs['terminal_failed']} 項同步工作已達自動重試上限",
            "detail": "；".join(
                f"{row.get('dataset')} {row.get('symbol')} {row.get('last_error') or '原因未記錄'}"
                for row in sync_jobs.get("failures", [])[:5]
                if row.get("attempts", 0) >= row.get("max_attempts", 3)
            ),
            "action": "正式推薦會依資料資格排除缺口股票；請檢視來源、錯誤與人工補齊策略。",
        })

    unhealthy_sources = [row for row in source_health if row.get("consecutive_failures", 0) >= 3]
    if unhealthy_sources:
        issues.append({
            "severity": "warning", "code": "unhealthy_data_sources",
            "title": f"{len(unhealthy_sources)} 個資料來源連續失敗",
            "detail": "；".join(
                f"{row['source']} / {row['dataset']}: {row.get('last_error') or 'unknown error'}"
                for row in unhealthy_sources[:5]
            ),
            "action": "檢查來源狀態與替代來源；未恢復前不得把受影響資料視為正式推薦依據。",
        })

    latest_error = str((latest_sync or {}).get("error") or "")
    watchlist_now_ready = False
    if latest_sync and latest_error == "watchlist_analysis":
        watchlist = database.list_watchlist()
        watchlist_now_ready = all(
            analysis_sync_plan(database, row["symbol"])["ready"] for row in watchlist
        )
        if watchlist_now_ready:
            resolved_since_sync.append("最近一次觀察股同步警告已由後續補齊修復")
    if latest_sync and latest_sync.get("status") in {"partial", "failed"} and not watchlist_now_ready:
        issues.append({
            "severity": "critical" if latest_sync["status"] == "failed" else "warning",
            "code": "daily_sync_incomplete",
            "title": "最近一次全站同步未完整完成",
            "detail": latest_sync.get("error") or "部分步驟未完成",
            "action": "檢查失敗步驟與資料日期後再採用最新推薦。",
        })
    if not latest_sync:
        issues.append({
            "severity": "warning",
            "code": "daily_sync_never_run",
            "title": "尚未執行全站收盤同步",
            "detail": "系統沒有每日同步紀錄。",
            "action": "先執行同步所有資料，再查看推薦結果。",
        })

    latest_steps = {}
    if latest_sync:
        try:
            latest_steps = json.loads(latest_sync.get("steps_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            latest_steps = {}
    market_step = latest_steps.get("market") or {}
    fallback_markets = [market for market in ("TWSE", "TPEx")
                        if (market_step.get(market) or {}).get("fallback_used")]
    if fallback_markets:
        issues.append({
            "severity": "warning", "code": "cached_fallback",
            "title": f"{', '.join(fallback_markets)} 目前使用本機快取",
            "detail": "官方即時來源最近同步失敗，系統保留最近成功資料且不偽裝為最新。",
            "action": "稍後重試官方來源；超過新鮮度門檻的股票會被排除正式推薦。",
        })

    critical = sum(issue["severity"] == "critical" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    status = "critical" if critical else "warning" if warnings else "healthy"
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "summary": {"critical": critical, "warning": warnings, "issues": len(issues)},
        "markets": markets,
        "quarantine": {
            "active": bool(quarantine_groups),
            "total_symbols": sum(row["lagging_count"] for row in quarantine_groups),
            "groups": quarantine_groups,
            "policy": "價格未對齊市場最新交易日的股票會自動隔離，不得進入當日排行榜或操作候選。",
        },
        "contracts": contracts,
        "latest_daily_sync": latest_sync,
        "queues": {"fundamentals": fundamental_queue, "prices": price_queue,
                   "sync_jobs": sync_jobs},
        "vnext_history_coverage": vnext_coverage,
        "sources": data_source_catalog(),
        "source_health": source_health,
        "resolved_since_sync": resolved_since_sync,
        "issues": issues,
        "recommendation_policy": {
            "formal_recommendations_require_complete_data": True,
            "message": "資料不足或過期的股票不得以預設分數代替，僅能列為觀察或資料不足。",
        },
    }


def capture_data_quality_snapshot(database: Database, target_limit: int = 100) -> dict:
    """Persist a read-only quality report for recommendation and backtest audit."""
    report = build_data_quality_report(database, target_limit)
    snapshot_id = database.save_data_quality_snapshot(
        report["generated_at"], report["status"], json.dumps(report, ensure_ascii=False, default=str)
    )
    return {"status": "completed", "snapshot_id": snapshot_id,
            "generated_at": report["generated_at"], "quality_status": report["status"],
            "contracts": report["contracts"]}
