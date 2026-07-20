from __future__ import annotations

from app.database import Database
from app.financials import analyze_financials


def _percentile(value: float | None, values: list[float], inverse: bool = False) -> float | None:
    if value is None or not values:
        return None
    ordered = sorted(values)
    below = sum(item < value for item in ordered)
    equal = sum(item == value for item in ordered)
    rank = (below + max(equal - 1, 0) / 2) / max(len(ordered) - 1, 1)
    return 1 - rank if inverse else rank


def _base_items(database: Database) -> list[dict]:
    items = []
    for row in database.get_screening_universe():
        financial = analyze_financials([row]) if row.get("fiscal_year") else {}
        item = {
            "symbol": row["symbol"], "name": row["name"], "market": row["market"],
            "industry": row["industry"], "close": row["close"],
            "revenue_yoy": row["yoy_percent"],
            "gross_margin": financial.get("gross_margin_percent"),
            "roe": financial.get("annualized_roe_percent"),
            "eps": financial.get("eps"),
            "debt_ratio": financial.get("debt_ratio_percent"),
            "pe": row["pe_ratio"] if row["pe_ratio"] and row["pe_ratio"] > 0 else None,
            "pb": row["pb_ratio"] if row["pb_ratio"] and row["pb_ratio"] > 0 else None,
            "dividend_yield": row["dividend_yield"],
        }
        fields = ("revenue_yoy", "gross_margin", "roe", "debt_ratio", "pe", "pb", "dividend_yield")
        item["completeness"] = round(sum(item[key] is not None for key in fields) / len(fields) * 100)
        items.append(item)
    return items


def recommend_stocks(
    database: Database,
    limit: int = 20,
    min_completeness: int = 70,
    profile: str = "balanced",
) -> list[dict]:
    """Rank research candidates using explainable quality, growth and value factors."""
    items = _base_items(database)
    keys = ("revenue_yoy", "gross_margin", "roe", "debt_ratio", "pe", "pb", "dividend_yield")
    universes = {key: [float(item[key]) for item in items if item[key] is not None] for key in keys}

    def ranked(item: dict, key: str, inverse: bool = False) -> float | None:
        # 財務比率優先和同產業比較；樣本過少時退回全市場，避免小樣本失真。
        peers = [
            float(peer[key]) for peer in items
            if peer[key] is not None and peer["industry"] == item["industry"]
        ]
        return _percentile(item[key], peers if len(peers) >= 5 else universes[key], inverse)
    results = []
    for item in items:
        if item["completeness"] < min_completeness:
            continue
        profitable = item["eps"] is not None and item["eps"] > 0
        profile_checks = {
            "balanced": True,
            "value": profitable and item["pe"] is not None and item["pe"] < 15
                     and item["pb"] is not None and item["pb"] < 2
                     and item["debt_ratio"] is not None and item["debt_ratio"] <= 70,
            "growth": profitable and item["revenue_yoy"] is not None
                      and item["revenue_yoy"] >= 20 and item["roe"] is not None
                      and item["roe"] > 0,
            "quality": profitable and item["roe"] is not None and item["roe"] >= 10
                       and item["gross_margin"] is not None and item["gross_margin"] > 0
                       and item["debt_ratio"] is not None and item["debt_ratio"] <= 60,
        }
        if not profile_checks.get(profile, False):
            continue
        ranks = {
            "revenue": ranked(item, "revenue_yoy"),
            "margin": ranked(item, "gross_margin"),
            "roe": ranked(item, "roe"),
            "debt": ranked(item, "debt_ratio", inverse=True),
            "pe": ranked(item, "pe", inverse=True),
            "pb": ranked(item, "pb", inverse=True),
            "yield": ranked(item, "dividend_yield"),
        }
        def rank(name: str) -> float:
            return ranks[name] if ranks[name] is not None else 0.0

        quality = (rank("roe") * 20 + rank("margin") * 10 + rank("debt") * 10)
        growth = rank("revenue") * 25
        value = rank("pe") * 15 + rank("pb") * 5 + rank("yield") * 5
        data_score = item["completeness"] / 100 * 10
        normalized = {
            "quality": quality / 40, "growth": growth / 25,
            "value": value / 25, "data": data_score / 10,
        }
        weights = {
            "balanced": {"quality": 40, "growth": 25, "value": 25, "data": 10},
            "value": {"quality": 25, "growth": 10, "value": 55, "data": 10},
            "growth": {"quality": 25, "growth": 50, "value": 15, "data": 10},
            "quality": {"quality": 55, "growth": 20, "value": 15, "data": 10},
        }[profile]
        score = round(sum(normalized[key] * weight for key, weight in weights.items()), 1)
        reasons = []
        risks = []
        if ranks["roe"] is not None and ranks["roe"] >= .7: reasons.append("ROE 位於市場前 30%")
        if ranks["revenue"] is not None and ranks["revenue"] >= .7: reasons.append("營收年增位於市場前 30%")
        if ranks["pe"] is not None and ranks["pe"] >= .7: reasons.append("本益比相對市場偏低")
        if ranks["debt"] is not None and ranks["debt"] >= .7: reasons.append("負債比相對市場偏低")
        if item["revenue_yoy"] is not None and item["revenue_yoy"] < 0: risks.append("最新月營收年減")
        if item["roe"] is not None and item["roe"] <= 0: risks.append("年化 ROE 非正值")
        if item["debt_ratio"] is not None and item["debt_ratio"] > 70: risks.append("負債比高於 70%")
        if ranks["roe"] is not None and ranks["roe"] >= .8 and item["debt_ratio"] and item["debt_ratio"] > 60:
            risks.append("高 ROE 可能受較高槓桿推升")
        if item["pe"] is None: risks.append("缺少有效正本益比")
        item.update({
            "score": score,
            "rating": "優先研究" if score >= 75 else "值得追蹤" if score >= 60 else "觀察",
            "quality_score": round(quality, 1), "growth_score": round(growth, 1),
            "value_score": round(value, 1), "data_score": round(data_score, 1),
            "reasons": reasons[:3] or ["綜合指標相對均衡"], "risks": risks,
            "profile": profile, "method_version": "fundamental-v2-summary-rules",
        })
        results.append(item)
    results.sort(key=lambda item: (item["score"], item["completeness"]), reverse=True)
    return results[:limit]
