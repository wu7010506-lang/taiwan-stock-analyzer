from __future__ import annotations

from statistics import mean


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_entry_plan(prices: list[dict], model_result: dict, strategy: dict) -> dict:
    """Turn a research candidate into an explainable, risk-budgeted entry plan.

    This is a planning aid, not an order instruction.  It deliberately refuses
    to infer a business thesis, management quality or catalyst from price data.
    """
    rows = [row for row in prices if _number(row.get("close")) is not None]
    if len(rows) < 20:
        return {"status": "insufficient_data", "reason": "fewer_than_20_price_sessions"}

    closes = [_number(row["close"]) for row in rows]
    latest = closes[-1]
    true_ranges: list[float] = []
    for index, row in enumerate(rows[-15:], max(0, len(rows) - 15)):
        high, low = _number(row.get("high")), _number(row.get("low"))
        previous = closes[index - 1] if index else latest
        if high is not None and low is not None:
            true_ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    atr = mean(true_ranges[-14:]) if true_ranges else None
    if not atr or atr <= 0:
        return {"status": "insufficient_data", "reason": "missing_ohlc_for_atr"}

    low_20 = min(_number(row.get("low")) or _number(row["close"]) for row in rows[-20:])
    ma20 = mean(closes[-20:])
    stop = max(low_20 * .99, latest - 2 * atr)
    risk_per_share = latest - stop
    if risk_per_share <= 0:
        return {"status": "insufficient_data", "reason": "invalid_invalidation_level"}
    risk_percent = risk_per_share / latest * 100
    risk_budget_percent = 0.5
    maximum_from_risk_budget = risk_budget_percent / risk_percent * 100
    model_cap = float(strategy.get("max_new_allocation_percent") or 0)
    suggested = round(min(model_cap, maximum_from_risk_budget, 10), 1)
    volume_20 = mean(_number(row.get("volume")) or 0 for row in rows[-20:])
    recent_volume = _number(rows[-1].get("volume")) or 0
    confirmation = latest >= ma20 and recent_volume >= volume_20 * .8
    blocked = model_result.get("action") not in {"buy", "accumulate", "hold"}
    if strategy.get("max_new_allocation_percent", 0) <= 0:
        blocked = True

    return {
        "status": "wait_for_confirmation" if not confirmation else "ready_for_review",
        "actionable": not blocked and confirmation and suggested > 0,
        "current_price": round(latest, 2),
        "entry_zone": {"low": round(max(ma20, latest - .5 * atr), 2),
                       "high": round(latest + .5 * atr, 2)},
        "invalidation_price": round(stop, 2),
        "risk_per_share": round(risk_per_share, 2),
        "risk_percent": round(risk_percent, 2),
        "illustrative_target_price": round(latest + 2 * risk_per_share, 2),
        "risk_reward_ratio": 2.0,
        "atr_14": round(atr, 2),
        "ma20": round(ma20, 2),
        "volume_confirmation": {
            "passed": recent_volume >= volume_20 * .8,
            "latest_volume": round(recent_volume), "average_20d_volume": round(volume_20),
        },
        "risk_budget_percent": risk_budget_percent,
        "suggested_initial_position_percent": suggested,
        "limitations": [
            "進場區與失效價依歷史價格波動推估，可能因跳空或流動性不足而無法成交。",
            "示意目標價以 2 倍風險距離計算，並非價格預測或報酬承諾。",
        ],
    }


def build_investment_checklist(model_result: dict, entry_plan: dict) -> dict:
    """Expose automatic evidence separately from analyst research still required."""
    quality = model_result.get("company_quality") or {}
    automatic = [
        {"id": "data_contract", "label": "資料契約與歷史完整度",
         "status": "passed" if model_result.get("eligibility", {}).get("formal_recommendation_allowed") else "failed"},
        {"id": "business_quality", "label": "企業品質分數至少 70",
         "status": "passed" if (quality.get("score") or 0) >= 70 else "failed"},
        {"id": "valuation", "label": "估值具安全邊際",
         "status": "passed" if (model_result.get("valuation_score") or 0) >= 60 else "review"},
        {"id": "entry_risk", "label": "技術確認與風險預算部位",
         "status": "passed" if entry_plan.get("actionable") else "review"},
        {"id": "crowding", "label": "法人擁擠／追價風險",
         "status": "failed" if model_result.get("crowding_risk") == "high" else "passed"},
    ]
    manual = [
        "商業模式與護城河是否可用一段話清楚說明？",
        "管理層資本配置與治理紀錄是否已由公開資料查核？",
        "投資論點的 3 至 7 項可觀察驗證指標與失效條件是否已記錄？",
        "近期法說、財報、除權息或重大事件風險是否已人工覆核？",
    ]
    return {"automatic": automatic, "manual_research_required": manual,
            "passed": sum(item["status"] == "passed" for item in automatic),
            "total": len(automatic)}
