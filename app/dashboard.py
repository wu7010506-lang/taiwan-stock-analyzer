from __future__ import annotations

from datetime import date, datetime
import json
from typing import Callable

from app.alerts import build_alerts
from app.data_quality import build_data_quality_report
from app.database import Database
from app.portfolio import portfolio_summary
from app.recommendation_gate import formal_recommendation_gate
from app.short_term_tracking import published_short_term_decisions
from app.technical_timing import assess_technical_timing


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
    short_term = _section(
        lambda: published_short_term_decisions(database, market_context, as_of_date, 10)
    )
    def cached_recommendations() -> dict:
        row = database.get_latest_vnext_recommendation_run()
        if not row:
            return {"status": "not_captured", "recommendations": [],
                    "message": "尚未建立 vNext 收盤推薦快照"}
        payload = json.loads(row["payload_json"])
        payload["recommendations"] = (payload.get("recommendations") or [])[:5]
        for recommendation in payload["recommendations"]:
            timing = assess_technical_timing(
                database.get_prices(recommendation["symbol"], 80), market_context
            )
            recommendation["technical_timing"] = timing
            recommendation["model_action"] = recommendation.get("action")
            if (recommendation.get("action") in {"buy", "accumulate"}
                    and timing["signal"] != "favorable"):
                recommendation["action"] = "wait"
                recommendation["technical_timing_constrained"] = True
        payload["cached_snapshot_date"] = row["snapshot_date"]
        payload["cached_at"] = row["created_at"]
        return payload

    recommendations = _section(cached_recommendations)
    # A formal-model rank answers which stocks deserve attention; it is not a
    # short-term entry instruction.  Surface those names in the short-term
    # panel so the user can follow them without conflating observation with a
    # buy signal from the still-research-only short-term rules.
    if short_term["status"] == "available" and recommendations["status"] == "available":
        snapshot = recommendations.get("data") or {}
        observations = []
        for rank, recommendation in enumerate(snapshot.get("recommendations") or [], start=1):
            timing = recommendation.get("technical_timing") or {}
            observations.append({
                "symbol": recommendation.get("symbol"),
                "name": recommendation.get("name"),
                "action": "observation",
                "source": "vnext_formal_model",
                "model_rank": rank,
                "as_of_date": snapshot.get("as_of_date") or snapshot.get("cached_snapshot_date"),
                "technical_as_of": timing.get("as_of"),
                "technical_signal": timing.get("signal"),
                "reason": "已通過正式模型與基本面資格；短線只列入觀察，等待固定規則出現可驗證的進場條件。",
                "risks": timing.get("risks") or [],
                "limitations": [
                    "短線策略仍為研究中，這不是買進指令。",
                    "模型排名不保證未來 3–10 個交易日報酬。",
                ],
            })
        short_term["data"]["model_observations"] = observations
    gate = formal_recommendation_gate(quality.get("data") or {})
    formal_actions_safe = gate["allowed"]
    unavailable = [name for name, section in {
        "quality": quality, "portfolio": portfolio, "alerts": alerts,
        "recommendations": recommendations, "short_term": short_term,
    }.items() if section["status"] == "unavailable"]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of_date.isoformat(),
        "market": market_context,
        "quality": quality,
        "portfolio": portfolio,
        "alerts": alerts,
        "short_term": short_term,
        "recommendations": recommendations,
        "decision_gate": {
            "formal_actions_safe": formal_actions_safe,
            "status": "open" if formal_actions_safe else "caution",
            "message": gate["message"],
            "reasons": gate["reasons"],
        },
        "unavailable_sections": unavailable,
    }
