from __future__ import annotations

from datetime import date, datetime
import json
from typing import Callable

from app.alerts import build_alerts
from app.data_quality import build_data_quality_report
from app.database import Database
from app.portfolio import portfolio_summary


def _section(loader: Callable[[], dict]) -> dict:
    try:
        return {"status": "available", "data": loader()}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc), "data": None}


def build_daily_dashboard(database: Database, market_context: dict,
                          as_of_date: date | None = None) -> dict:
    """Compose daily decisions without allowing one failed section to hide the rest."""
    as_of_date = as_of_date or date.today()
    quality = _section(lambda: build_data_quality_report(database))
    portfolio = _section(lambda: portfolio_summary(database, market_context, as_of_date))
    alerts = _section(lambda: build_alerts(database, "long", market_context))
    def cached_recommendations() -> dict:
        row = database.get_latest_vnext_recommendation_run()
        if not row:
            return {"status": "not_captured", "recommendations": [],
                    "message": "尚未建立 vNext 收盤推薦快照"}
        payload = json.loads(row["payload_json"])
        payload["recommendations"] = (payload.get("recommendations") or [])[:5]
        payload["cached_snapshot_date"] = row["snapshot_date"]
        payload["cached_at"] = row["created_at"]
        return payload

    recommendations = _section(cached_recommendations)
    quality_status = (quality.get("data") or {}).get("status")
    formal_actions_safe = quality_status == "healthy"
    unavailable = [name for name, section in {
        "quality": quality, "portfolio": portfolio, "alerts": alerts,
        "recommendations": recommendations,
    }.items() if section["status"] == "unavailable"]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of_date.isoformat(),
        "market": market_context,
        "quality": quality,
        "portfolio": portfolio,
        "alerts": alerts,
        "recommendations": recommendations,
        "decision_gate": {
            "formal_actions_safe": formal_actions_safe,
            "status": "open" if formal_actions_safe else "caution",
            "message": ("資料品質檢查正常，可繼續閱讀個別建議。" if formal_actions_safe
                        else "資料品質仍有警告；建議僅供研究，交易前需核對資料日期。"),
        },
        "unavailable_sections": unavailable,
    }
