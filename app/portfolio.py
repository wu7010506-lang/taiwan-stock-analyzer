from __future__ import annotations

from collections import defaultdict
from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.database import Database
from app.vnext_model import evaluate_vnext_stock


class PositionUpdate(BaseModel):
    average_cost: float | None = Field(None, gt=0)
    shares: int | None = Field(None, ge=0)
    purchase_date: str | None = None
    stop_loss: float | None = Field(None, gt=0)
    target_price: float | None = Field(None, gt=0)
    investment_horizon: str | None = Field(None, pattern="^(short|long)$")
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_position(self):
        if (self.shares or 0) > 0 and self.average_cost is None:
            raise ValueError("持有股數大於零時必須填寫平均成本")
        if self.stop_loss and self.target_price and self.stop_loss >= self.target_price:
            raise ValueError("停損價必須低於目標價")
        return self


def _market_strategy(context: dict) -> dict:
    """Convert market conditions into an explainable portfolio playbook."""
    market_score = float(context.get("market_score", 50))
    overheat_score = float(context.get("overheat_score", 0))
    if overheat_score >= 70:
        return {"id": "extreme_overheat", "name": "過熱防守", "cash_target_percent": 60,
                "max_total_exposure_percent": 40, "max_new_allocation_percent": 0, "allow_small_build": False}
    if market_score < 40:
        return {"id": "risk_off", "name": "防守式分批布局", "cash_target_percent": 60,
                "max_total_exposure_percent": 40, "max_new_allocation_percent": 2, "allow_small_build": True}
    if overheat_score >= 45:
        return {"id": "overheated", "name": "獲利保護", "cash_target_percent": 40,
                "max_total_exposure_percent": 60, "max_new_allocation_percent": 2, "allow_small_build": False}
    if market_score >= 60:
        return {"id": "risk_on", "name": "順勢成長", "cash_target_percent": 20,
                "max_total_exposure_percent": 80, "max_new_allocation_percent": 7, "allow_small_build": False}
    return {"id": "neutral", "name": "均衡分批布局", "cash_target_percent": 30,
            "max_total_exposure_percent": 70, "max_new_allocation_percent": 5, "allow_small_build": False}


def _position_decision(row: dict, model_result: dict | None, market_context: dict) -> dict:
    if row["stop_triggered"]:
        return {
            "action": "sell",
            "source": "risk_control",
            "reasons": ["stop_loss_triggered"],
            "risks": [],
            "new_allocation_percent": 0,
        }
    if row["target_reached"]:
        return {
            "action": "reduce",
            "source": "risk_control",
            "reasons": ["target_price_reached"],
            "risks": [],
            "new_allocation_percent": 0,
        }
    if row["portfolio_weight_percent"] > 10:
        return {
            "action": "reduce",
            "source": "portfolio_risk",
            "reasons": ["single_stock_limit_exceeded"],
            "risks": [],
            "new_allocation_percent": 0,
        }
    if not model_result or model_result["action"] == "insufficient_data":
        return {
            "action": "insufficient_data",
            "source": "vnext",
            "reasons": ["insufficient_vnext_data"],
            "risks": model_result.get("risks", []) if model_result else [],
            "new_allocation_percent": 0,
        }

    action = model_result["action"]
    if action in {"buy", "accumulate"}:
        action = "add"
    market_score = float(market_context.get("market_score", 50))
    overheat_score = float(market_context.get("overheat_score", 0))
    risks = list(model_result.get("risks", []))
    if action == "add" and (market_score < 40 or overheat_score >= 70):
        action = "wait"
        risks.append("market_risk_off")
    allocation = round(max(0, min(10 - row["portfolio_weight_percent"], 5)), 1)
    return {
        "action": action,
        "source": "vnext",
        "reasons": list(model_result.get("supporting_reasons", [])),
        "risks": risks,
        "new_allocation_percent": allocation if action == "add" else 0,
        "value_score": model_result.get("value_score"),
        "timing_score": model_result.get("timing_score"),
        "confidence": model_result.get("confidence"),
        "crowding_risk": model_result.get("crowding_risk"),
    }


def _watching_decision(model_result: dict, market_context: dict, strategy: dict) -> dict:
    if model_result["action"] == "insufficient_data":
        return {
            "action": "insufficient_data", "source": "vnext",
            "reasons": ["insufficient_vnext_data"], "risks": model_result["risks"],
            "new_allocation_percent": 0,
        }
    value_score = model_result.get("value_score") or 0
    if model_result.get("model") == "vnext_observation":
        action = "short_history_watch"
        allocation = 0
        if (strategy["id"] == "risk_off" and value_score >= 65
                and "market_extreme_overheat" not in model_result.get("risks", [])):
            action = "short_history_build"
            allocation = 1
        return {
            "action": action, "source": "vnext_observation",
            "reasons": list(model_result.get("supporting_reasons", [])),
            "risks": list(model_result.get("risks", [])),
            "new_allocation_percent": allocation,
            "value_score": model_result.get("value_score"),
            "timing_score": model_result.get("timing_score"),
            "confidence": "low", "crowding_risk": "unknown",
            "data_quality": model_result.get("data_quality"),
        }
    action = "buy" if model_result["action"] in {"buy", "accumulate"} else "wait"
    risks = list(model_result.get("risks", []))
    reasons = list(model_result.get("supporting_reasons", []))
    if (strategy["allow_small_build"] and value_score >= 65
            and model_result["action"] in {"hold", "buy", "accumulate"}
            and model_result.get("crowding_risk") != "high"):
        action = "build_small"
        reasons.append("risk_off_quality_candidate")
    elif action == "buy" and strategy["max_new_allocation_percent"] == 0:
        action = "wait"
        risks.append("market_overheat")
    elif action == "buy" and strategy["id"] == "risk_off":
        action = "wait"
        risks.append("market_risk_off")
    return {
        "action": action, "source": "vnext",
        "reasons": reasons, "risks": risks,
        "new_allocation_percent": (
            strategy["max_new_allocation_percent"] if action in {"buy", "build_small"} else 0
        ),
        "value_score": model_result.get("value_score"),
        "timing_score": model_result.get("timing_score"),
        "confidence": model_result.get("confidence"),
        "crowding_risk": model_result.get("crowding_risk"),
    }
    return {
        "action": "hold",
        "source": "portfolio_default",
        "reasons": ["no_exit_signal"],
        "risks": [],
        "new_allocation_percent": 0,
    }


def portfolio_summary(
    database: Database,
    market_context: dict | None = None,
    as_of_date: date | None = None,
) -> dict:
    market_context = market_context or {}
    strategy = _market_strategy(market_context)
    as_of_date = as_of_date or date.today()
    rows = database.list_watchlist()
    held = [row for row in rows if row["is_held"] and row["market_value"] is not None]
    total_cost = sum(row["cost_basis"] for row in held)
    total_value = sum(row["market_value"] for row in held)
    profit = total_value - total_cost
    industries: dict[str, float] = defaultdict(float)
    for row in held:
        industries[row["industry"] or "未分類"] += row["market_value"]
    exposure = sorted(({"industry": industry, "market_value": value,
                        "weight_percent": value / total_value * 100 if total_value else 0}
                       for industry, value in industries.items()),
                      key=lambda item: item["market_value"], reverse=True)
    warnings = []
    for row in held:
        weight = row["market_value"] / total_value * 100 if total_value else 0
        row["portfolio_weight_percent"] = weight
        model_result = evaluate_vnext_stock(
            database, row["symbol"], as_of_date, market_context
        )
        row["portfolio_decision"] = _position_decision(row, model_result, market_context)
        if weight > 10:
            warnings.append(f"{row['symbol']} {row['name']} 占投資組合 {weight:.1f}%，集中度偏高")
        if row["stop_triggered"]:
            warnings.append(f"{row['symbol']} {row['name']} 已跌破設定停損價")
        if row["target_reached"]:
            warnings.append(f"{row['symbol']} {row['name']} 已達設定目標價")
    for item in exposure:
        if item["weight_percent"] > 25:
            warnings.append(f"產業 {item['industry']} 占 {item['weight_percent']:.1f}%，產業集中度偏高")
    decision_counts: dict[str, int] = defaultdict(int)
    for row in held:
        decision_counts[row["portfolio_decision"]["action"]] += 1
    watching_decisions = []
    for row in rows:
        if row["is_held"]:
            continue
        model_result = evaluate_vnext_stock(
            database, row["symbol"], as_of_date, market_context
        )
        decision = _watching_decision(model_result, market_context, strategy)
        watching_decisions.append({
            "symbol": row["symbol"], "name": row["name"], "decision": decision,
        })
        decision_counts[decision["action"]] += 1
    return {"watching_count": len(rows), "held_count": len(held),
            "total_cost": total_cost, "total_market_value": total_value,
            "unrealized_profit": profit,
            "unrealized_return_percent": profit / total_cost * 100 if total_cost else None,
            "largest_position_percent": max((row["portfolio_weight_percent"] for row in held),
                                             default=0),
            "industry_exposure": exposure, "warnings": warnings, "positions": held,
            "market_regime": market_context.get("regime", "unknown"),
            "market_score": market_context.get("market_score"),
            "market_strategy": strategy,
            "risk_limits": {"single_stock_limit_percent": 10,
                            "industry_limit_percent": 25,
                            "target_cash_percent": strategy["cash_target_percent"],
                            "max_total_exposure_percent": strategy["max_total_exposure_percent"]},
            "decision_counts": dict(decision_counts),
            "watching_decisions": watching_decisions}
