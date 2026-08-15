from __future__ import annotations

from collections import defaultdict
from statistics import mean

from app.database import Database
from app.performance import TRACKED_FACTORS, model_performance
from app.recommendations import PROFILE_WEIGHTS


FACTOR_LABELS = {
    "business_quality_score": "企業品質",
    "cashflow_quality_score": "現金流品質",
    "durability_score": "獲利持續性",
    "value_score": "估值",
    "risk_resilience_score": "風險韌性",
    "growth_quality_score": "成長品質",
    "market_score": "市場配適",
    "quality_score": "品質",
    "technical_score": "技術動能",
    "chip_score": "法人籌碼",
    "liquidity_score": "流動性",
    "news_score": "時事",
}

PROFILE_FACTOR_KEYS = {
    "business_quality": "business_quality_score",
    "cashflow_quality": "cashflow_quality_score",
    "durability": "durability_score",
    "value": "value_score",
    "risk_resilience": "risk_resilience_score",
    "growth_quality": "growth_quality_score",
    "market": "market_score",
    "market_fit": "market_score",
}


def _average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = (index + 1 + end) / 2
        for position in range(index, end):
            ranks[ordered[position][0]] = average_rank
        index = end
    return ranks


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = (
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    ) ** .5
    return numerator / denominator if denominator else None


def _weighted_score(factors: dict, weights: dict[str, float]) -> float | None:
    available = [(PROFILE_FACTOR_KEYS[key], weight) for key, weight in weights.items()
                 if factors.get(PROFILE_FACTOR_KEYS.get(key, "")) is not None]
    total_weight = sum(weight for _, weight in available)
    if not available or not total_weight:
        return None
    return sum(float(factors[key]) * weight for key, weight in available) / total_weight


def _scenario_metrics(matured: list[dict], weights: dict[str, float]) -> dict:
    pairs = []
    for row in matured:
        score = _weighted_score(row.get("factors") or {}, weights)
        if score is not None:
            pairs.append((score, float(row["return_percent"])))
    if len(pairs) < 3:
        return {"sample_size": len(pairs), "rank_ic": None,
                "top_quintile_return_percent": None}
    scores = [row[0] for row in pairs]
    returns = [row[1] for row in pairs]
    top_count = max(1, len(pairs) // 5)
    top_returns = [row[1] for row in sorted(pairs, reverse=True)[:top_count]]
    return {
        "sample_size": len(pairs),
        "rank_ic": _correlation(_average_ranks(scores), _average_ranks(returns)),
        "top_quintile_return_percent": mean(top_returns),
    }


def _weight_sensitivity(matured: list[dict], profile: str,
                        minimum_sample: int) -> list[dict]:
    base = PROFILE_WEIGHTS.get(profile)
    if not base:
        return []
    scenarios = [("baseline", "目前權重", dict(base), None)]
    for factor in base:
        adjusted = dict(base)
        adjusted[factor] += 10
        total = sum(adjusted.values())
        adjusted = {key: value / total * 100 for key, value in adjusted.items()}
        label = FACTOR_LABELS.get(PROFILE_FACTOR_KEYS[factor], factor)
        scenarios.append((f"plus_10_{factor}", f"提高{label}", adjusted, factor))
    result = []
    for scenario_id, label, weights, changed_factor in scenarios:
        metrics = _scenario_metrics(matured, weights)
        result.append({
            "scenario": scenario_id, "label": label,
            "changed_factor": changed_factor,
            "weights": {key: round(value, 2) for key, value in weights.items()},
            **metrics,
            "status": "testable" if metrics["sample_size"] >= minimum_sample else "insufficient_sample",
        })
    return result


def factor_validation_report(database: Database, profile: str = "evidence_based",
                             horizon: int = 20, minimum_sample: int = 20) -> dict:
    """Evaluate stored point-in-time factor scores against later realised returns."""
    performance = model_performance(database, profile, horizon, min_score=0)
    matured = [row for row in performance["outcomes"] if row.get("matured")]
    factors = []
    for name in TRACKED_FACTORS:
        pairs = [(float(row["factors"][name]), float(row["return_percent"]))
                 for row in matured if row.get("factors", {}).get(name) is not None]
        values = [pair[0] for pair in pairs]
        returns = [pair[1] for pair in pairs]
        information_coefficient = _correlation(_average_ranks(values), _average_ranks(returns))
        ordered = sorted(pairs, key=lambda pair: pair[0])
        bucket = max(1, len(ordered) // 5)
        low = [item[1] for item in ordered[:bucket]]
        high = [item[1] for item in ordered[-bucket:]]
        spread = mean(high) - mean(low) if len(ordered) >= 10 else None
        factors.append({
            "factor": name,
            "label": FACTOR_LABELS.get(name, name),
            "sample_size": len(pairs),
            "information_coefficient": information_coefficient,
            "high_minus_low_return_percent": spread,
            "status": "testable" if len(pairs) >= minimum_sample else "insufficient_sample",
        })

    regime_rows: dict[str, list[float]] = defaultdict(list)
    for row in matured:
        regime_rows[row.get("market_regime") or "未知"].append(float(row["return_percent"]))
    regimes = [{"regime": regime, "sample_size": len(values),
                "average_return_percent": mean(values),
                "win_rate_percent": sum(value > 0 for value in values) / len(values) * 100}
               for regime, values in sorted(regime_rows.items())]
    sufficient = sum(item["status"] == "testable" for item in factors)
    sensitivity = _weight_sensitivity(matured, profile, minimum_sample)
    return {
        "mode": "factor_validation", "profile": profile, "horizon": horizon,
        "minimum_sample": minimum_sample, "matured_signals": len(matured),
        "testable_factors": sufficient, "factors": factors, "market_regimes": regimes,
        "weight_sensitivity": sensitivity,
        "conclusion": ("樣本足以開始比較因子，但仍不能視為因果或未來報酬保證。"
                       if sufficient else "成熟樣本不足，僅顯示資料累積進度，不調整模型權重。"),
        "limitations": [
            "因子診斷只使用當時保存的推薦快照，避免以今日分數回填過去。",
            "樣本來自模型曾評估的股票，不等同完整市場橫斷面。",
            "未達最低樣本數時禁止據此自動調整權重。",
        ],
    }
