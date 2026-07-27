from __future__ import annotations

from datetime import datetime
import json

from app.database import Database
from app.source_policy import data_source_catalog


DATASET_LABELS = {
    "prices": "日價量",
    "revenues": "月營收",
    "valuations": "估值",
    "financials": "財報",
    "institutions": "法人買賣",
}


def build_data_quality_report(database: Database, target_limit: int = 100) -> dict:
    """Build one read-only report for freshness, coverage and failed sync jobs."""
    database.initialize()
    markets = database.get_market_data_freshness()
    latest_sync = database.get_latest_daily_sync_run()
    fundamental_queue = database.get_fundamental_sync_progress(target_limit)
    price_queue = database.get_price_sync_progress(target_limit)
    issues: list[dict] = []

    for market, datasets in markets.items():
        for dataset, details in datasets.items():
            coverage = float(details.get("coverage_percent") or 0)
            if coverage >= 95:
                continue
            severity = "critical" if coverage < 70 else "warning"
            issues.append({
                "severity": severity,
                "code": "low_coverage",
                "market": market,
                "dataset": dataset,
                "title": f"{market} {DATASET_LABELS.get(dataset, dataset)}覆蓋率不足",
                "detail": (
                    f"最新一期 {details.get('latest_date') or '未知'} 僅覆蓋 "
                    f"{details.get('covered_stocks', 0)}/{details.get('total_stocks', 0)} 檔"
                ),
                "action": "重新同步；若持續失敗，正式推薦應排除缺漏股票。",
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
                "title": f"{queue_label}有 {failed} 檔同步失敗",
                "detail": "；".join(
                    f"{row.get('symbol')} {row.get('error') or '原因未記錄'}"
                    for row in (queue.get("failures") or [])[:5]
                ),
                "action": "稍後重試失敗批次，並保留錯誤原因供資料源替代判斷。",
            })

    if latest_sync and latest_sync.get("status") in {"partial", "failed"}:
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
        "latest_daily_sync": latest_sync,
        "queues": {"fundamentals": fundamental_queue, "prices": price_queue},
        "sources": data_source_catalog(),
        "issues": issues,
        "recommendation_policy": {
            "formal_recommendations_require_complete_data": True,
            "message": "資料不足或過期的股票不得以預設分數代替，僅能列為觀察或資料不足。",
        },
    }
