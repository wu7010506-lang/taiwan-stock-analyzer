from __future__ import annotations

from bisect import bisect_left, bisect_right

from app.database import Database
from app.financials import analyze_financials
from app.market_context import get_market_context
from app.evidence_model import build_fundamental_evidence
from app.historical_valuation import build_historical_valuations
from app.industry_model import industry_category, industry_label


PROFILE_WEIGHTS = {
    "balanced": {"quality": 25, "value": 20, "technical": 15,
                 "revenue_growth": 15, "chip": 8, "liquidity": 7,
                 "market": 7, "news": 3},
    "value": {"quality": 25, "growth": 5, "annual_growth": 10,
              "value": 30, "technical": 15, "chip": 4,
              "market": 4, "news": 2, "liquidity": 5},
    "growth": {"quality": 20, "growth": 20, "annual_growth": 10,
               "value": 10, "technical": 20, "chip": 5,
               "market": 5, "news": 2, "liquidity": 8},
    "quality": {"quality": 35, "growth": 7, "annual_growth": 10,
                "value": 20, "technical": 15, "chip": 3,
                "market": 3, "news": 2, "liquidity": 5},
    "long_term_quality": {"quality": 30, "durability": 15, "value": 15,
                          "scale": 20, "revenue_growth": 5, "technical": 3,
                          "liquidity": 7, "market": 3, "chip": 1, "news": 1},
    "evidence_based": {"business_quality": 30, "cashflow_quality": 20,
                       "durability": 15, "value": 15, "risk_resilience": 10,
                       "growth_quality": 5, "market_fit": 5},
}


def _evidence_exclusion_reasons(item: dict) -> list[str]:
    """Return non-negotiable evidence-based research exclusions.

    These are eligibility checks, not score penalties: a company with an
    unsafe balance sheet or currently negative free cash flow must not be
    promoted by strong historical or cross-sectional factors.
    """
    reasons = list(item.get("financial_integrity_issues") or [])
    debt_ratio = item.get("latest_debt_ratio")
    if debt_ratio is not None and float(debt_ratio) > 70:
        reasons.append("latest_debt_ratio_above_70")
    latest_fcf = item.get("latest_free_cash_flow")
    if latest_fcf is not None and float(latest_fcf) < 0:
        reasons.append("latest_free_cash_flow_negative")
    return reasons


def _percentile(value: float | None, values: list[float], inverse: bool = False) -> float | None:
    if value is None or not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return .5
    below = bisect_left(ordered, value)
    equal = bisect_right(ordered, value) - below
    rank = (below + max(equal - 1, 0) / 2) / max(len(ordered) - 1, 1)
    return 1 - rank if inverse else rank


def _change(current: float | None, previous: float | None) -> float | None:
    return None if current is None or previous in (None, 0) else (current / previous - 1) * 100


def _base_items(database: Database) -> list[dict]:
    items = []
    for row in database.get_screening_universe():
        financial = analyze_financials([row]) if row.get("fiscal_year") else {}
        close = row["close"]
        item = {
            "symbol": row["symbol"], "name": row["name"], "market": row["market"],
            "industry": row["industry"], "close": close, "trade_date": row["trade_date"],
            "turnover": row["turnover"], "revenue_yoy": row["yoy_percent"],
            "annual_revenue_yoy": row["annual_revenue_yoy"],
            "gross_margin": financial.get("gross_margin_percent"),
            "roe": financial.get("annualized_roe_percent"), "eps": financial.get("eps"),
            "debt_ratio": financial.get("debt_ratio_percent"),
            "pe": row["pe_ratio"] if row["pe_ratio"] and row["pe_ratio"] > 0 else None,
            "pb": row["pb_ratio"] if row["pb_ratio"] and row["pb_ratio"] > 0 else None,
            "dividend_yield": row["dividend_yield"],
            "momentum_5d": _change(close, row["close_5d_ago"]),
            "above_ma20": None if close is None or row["ma20"] is None else close >= row["ma20"],
            "drawdown_52w": _change(close, row["high_52w"]),
            "foreign_net": row["foreign_net"], "trust_net": row["trust_net"],
            "foreign_net_5d": row["foreign_net_5d"], "trust_net_5d": row["trust_net_5d"],
            "volume_5d": row["volume_5d"], "turnover_ratio_20d": row["turnover_ratio_20d"],
            "financial_revenue": row["revenue"], "equity": row["equity"],
            "financial_periods_count": row["financial_periods_count"],
            "positive_eps_periods": row["positive_eps_periods"],
            "profitable_years": row["profitable_years"], "dividend_years": row["dividend_years"],
        }
        fields = ("revenue_yoy", "gross_margin", "roe", "debt_ratio", "pe", "pb",
                  "dividend_yield", "momentum_5d", "above_ma20", "turnover")
        item["completeness"] = round(sum(item[key] is not None for key in fields) / len(fields) * 100)
        items.append(item)
    return items


def recommend_stocks(
    database: Database, limit: int = 20, min_completeness: int = 70,
    profile: str = "balanced", context: dict | None = None,
) -> list[dict]:
    """Rank candidates with fundamentals, price, flow, market regime and official events."""
    items = _base_items(database)
    evidence = build_fundamental_evidence(database)
    historical_valuations = build_historical_valuations(database)
    for item in items:
        item.update(evidence.get(item["symbol"], {}))
        item.update(historical_valuations.get(item["symbol"], {}))
        item["industry_category"] = industry_category(item.get("industry"))
        item["industry_model"] = industry_label(item.get("industry"))
        if item["industry_category"] == "financial":
            item["evidence_ready"] = bool(
                (item.get("evidence_years") or 0) >= 5
                and (item.get("annual_periods") or 0) >= 4
            )
        for key in ("median_roe_annual", "median_operating_margin", "median_fcf_margin",
                    "cash_conversion", "positive_fcf_ratio", "profitable_year_ratio",
                    "positive_eps_year_ratio", "revenue_cagr_annual", "latest_debt_ratio",
                    "margin_variation", "roe_variation"):
            item.setdefault(key, None)
        item.setdefault("financial_integrity_issues", [])
    if not items:
        return []
    context = context if context is not None else get_market_context()
    keys = ("revenue_yoy", "annual_revenue_yoy", "gross_margin", "roe", "debt_ratio", "pe", "pb",
            "dividend_yield", "momentum_5d", "turnover", "foreign_net", "trust_net",
            "financial_revenue", "equity", "median_roe_annual",
            "median_operating_margin", "median_fcf_margin", "cash_conversion",
            "positive_fcf_ratio", "profitable_year_ratio", "positive_eps_year_ratio",
            "revenue_cagr_annual", "latest_debt_ratio", "margin_variation",
            "roe_variation")
    universes = {
        key: sorted(float(item[key]) for item in items if item[key] is not None)
        for key in keys
    }
    industry_universes: dict[str | None, dict[str, list[float]]] = {}
    for item in items:
        industry = item.get("industry")
        bucket = industry_universes.setdefault(industry, {key: [] for key in keys})
        for key in keys:
            if item[key] is not None:
                bucket[key].append(float(item[key]))
    for bucket in industry_universes.values():
        for values in bucket.values():
            values.sort()
    events_by_symbol: dict[str, list[dict]] = {}
    for event in context.get("events", []):
        events_by_symbol.setdefault(event["symbol"], []).append(event)

    def ranked(item: dict, key: str, inverse: bool = False) -> float | None:
        peers = industry_universes.get(item.get("industry"), {}).get(key, [])
        return _percentile(item[key], peers if len(peers) >= 5 else universes[key], inverse)

    results = []
    for item in items:
        if item["completeness"] < min_completeness:
            continue
        # A unit-scale anomaly invalidates every score derived from the latest
        # financial statement, regardless of the selected research profile.
        if item.get("financial_integrity_issues"):
            continue
        profitable = item["eps"] is not None and item["eps"] > 0
        checks = {
            "balanced": True,
            "value": profitable and item["pe"] is not None and item["pe"] < 15
                     and item["pb"] is not None and item["pb"] < 2
                     and item["debt_ratio"] is not None and item["debt_ratio"] <= 70,
            "growth": profitable and item["revenue_yoy"] is not None
                      and item["revenue_yoy"] >= 20 and item["roe"] is not None and item["roe"] > 0,
            "quality": profitable and item["roe"] is not None and item["roe"] >= 10
                       and item["gross_margin"] is not None and item["gross_margin"] > 0
                       and item["debt_ratio"] is not None and item["debt_ratio"] <= 60,
            "long_term_quality": profitable and item["debt_ratio"] is not None
                                 and item["debt_ratio"] <= 70,
            "evidence_based": bool(item.get("evidence_ready")),
        }
        if not checks.get(profile, False):
            continue
        if profile == "evidence_based" and _evidence_exclusion_reasons(item):
            continue
        ranks = {key: ranked(item, key, key in {"debt_ratio", "latest_debt_ratio", "pe", "pb"})
                 for key in keys}
        rank = lambda name, default=.5: ranks[name] if ranks[name] is not None else default
        quality = (rank("roe") * .5 + rank("gross_margin") * .25 + rank("debt_ratio") * .25) * 100
        growth = rank("revenue_yoy") * 100
        annual_growth = rank("annual_revenue_yoy") * 100
        revenue_growth = (growth + annual_growth) / 2
        value = (rank("pe") * .55 + rank("pb") * .2 + rank("dividend_yield") * .25) * 100
        cross_sectional_value = value
        if profile == "evidence_based" and item.get("historical_value_score") is not None:
            value = item["historical_value_score"] * .7 + cross_sectional_value * .3
        trend_parts = [rank("momentum_5d")]
        if item["above_ma20"] is not None:
            trend_parts.append(.75 if item["above_ma20"] else .25)
        if item["drawdown_52w"] is not None:
            trend_parts.append(max(0, min(1, 1 + item["drawdown_52w"] / 35)))
        technical = sum(trend_parts) / len(trend_parts) * 100
        flow_values = [ranks[key] for key in ("foreign_net", "trust_net") if ranks[key] is not None]
        chip = (sum(flow_values) / len(flow_values) * 100) if flow_values else 50.0
        market = float(context.get("market_score", 50))
        company_events = events_by_symbol.get(item["symbol"], [])
        event_delta = sum(event.get("sentiment", 0) for event in company_events)
        news = max(0, min(100, 50 + event_delta))
        liquidity = rank("turnover") * 100
        scale = (rank("financial_revenue") * .6 + rank("equity") * .4) * 100
        history_periods = int(item["financial_periods_count"] or 0)
        if history_periods >= 3:
            profit_consistency = int(item["positive_eps_periods"] or 0) / history_periods * 100
            year_bonus = min(int(item["profitable_years"] or 0) / 5, 1) * 100
            dividend_bonus = min(int(item["dividend_years"] or 0) / 5, 1) * 100
            durability = profit_consistency * .6 + year_bonus * .25 + dividend_bonus * .15
            durability_coverage = min(100, round(history_periods / 20 * 100))
        else:
            durability, durability_coverage = 50.0, round(history_periods / 3 * 40)

        def bounded(value: float | None, low: float, high: float, default: float = 50) -> float:
            if value is None:
                return default
            return max(0, min(100, (value - low) / (high - low) * 100))

        business_quality = (
            rank("median_roe_annual") * 40
            + rank("median_operating_margin") * 25
            + rank("margin_variation") * 15
            + rank("latest_debt_ratio") * 20
        )
        cashflow_quality = (
            bounded(item.get("positive_fcf_ratio"), .4, 1) * .4
            + bounded(item.get("cash_conversion"), .5, 1.5) * .3
            + rank("median_fcf_margin") * 30
        )
        evidence_durability = (
            bounded(item.get("positive_eps_year_ratio"), .5, 1) * .35
            + bounded(item.get("profitable_year_ratio"), .5, 1) * .30
            + bounded(min((item.get("dividend_years") or 0) / 5, 1), .2, 1) * .20
            + rank("roe_variation") * 15
        )
        growth_quality = (
            rank("revenue_cagr_annual") * .45
            + rank("annual_revenue_yoy") * .20
            + bounded(item.get("positive_fcf_ratio"), .4, 1) / 100 * .35
        ) * 100
        # A growth signal unsupported by cash generation cannot receive a high growth score.
        if (item.get("positive_fcf_ratio") or 0) < .5:
            growth_quality = min(growth_quality, 45)
        risk_resilience = (
            rank("latest_debt_ratio") * .35 + rank("margin_variation") * .25
            + rank("roe_variation") * .15
            + bounded(item.get("positive_fcf_ratio"), .4, 1) / 100 * .25
        ) * 100
        industry_adjustments = []
        cycle_peak_risk = False
        if item["industry_category"] == "financial":
            # Operating cash flow and debt ratios are not comparable for banks/insurers.
            business_quality = (
                rank("median_roe_annual") * .55 + rank("roe_variation") * .20
                + bounded(item.get("profitable_year_ratio"), .5, 1) / 100 * .25
            ) * 100
            cashflow_quality = (
                rank("roe_variation") * .40
                + bounded(item.get("profitable_year_ratio"), .5, 1) / 100 * .35
                + bounded(min((item.get("dividend_years") or 0) / 5, 1), .2, 1) / 100 * .25
            ) * 100
            risk_resilience = (
                rank("roe_variation") * .35
                + bounded(item.get("profitable_year_ratio"), .5, 1) / 100 * .35
                + rank("equity") * .30
            ) * 100
            growth_quality = 50.0
            industry_adjustments.append("金融業不使用一般公司的負債率與自由現金流標準")
        elif item["industry_category"] == "semiconductor":
            cashflow_quality = (
                bounded(item.get("positive_fcf_ratio"), .3, 1) * .20
                + bounded(item.get("cash_conversion"), .5, 1.5) * .45
                + rank("median_fcf_margin") * 35
            )
            industry_adjustments.append("半導體提高現金轉換權重，降低擴產期資本支出的懲罰")
        elif item["industry_category"] == "cyclical":
            cycle_peak_risk = bool(
                (item.get("annual_revenue_yoy") or 0) > 20
                and (item.get("revenue_cagr_annual") or 0) < 8
                and (item.get("margin_variation") or 0) > .20
            )
            if cycle_peak_risk:
                growth_quality = min(growth_quality, 40)
                industry_adjustments.append("短期成長高於長期趨勢，可能處於景氣循環高峰")
        market_fit = market

        institution_net_5d = float(item["foreign_net_5d"] or 0) + float(item["trust_net_5d"] or 0)
        institution_net_ratio = (institution_net_5d / float(item["volume_5d"]) * 100
                                 if item["volume_5d"] else None)
        influence_points = 0
        influence_reasons = []
        if item["momentum_5d"] is not None and item["momentum_5d"] >= 8:
            influence_points += 25; influence_reasons.append(f"近5日上漲 {item['momentum_5d']:.1f}%")
        if institution_net_ratio is not None and institution_net_ratio >= 10:
            influence_points += 40; influence_reasons.append(f"法人5日買超占成交量 {institution_net_ratio:.1f}%")
        elif institution_net_ratio is not None and institution_net_ratio >= 5:
            influence_points += 25; influence_reasons.append(f"法人5日買超占成交量 {institution_net_ratio:.1f}%")
        if item["turnover_ratio_20d"] is not None and item["turnover_ratio_20d"] >= 1.8:
            influence_points += 20; influence_reasons.append(f"成交金額為20日均值 {item['turnover_ratio_20d']:.1f} 倍")
        weak_fundamentals = quality < 45 or growth < 35
        speculation_points = influence_points
        if weak_fundamentals and influence_points >= 25:
            speculation_points += 25; influence_reasons.append("基本面或營收尚未跟上價格與籌碼")
        if value < 25 and influence_points >= 25:
            speculation_points += 10; influence_reasons.append("估值相對昂貴")
        influence_label = "高" if influence_points >= 60 else "中" if influence_points >= 30 else "低"
        speculation_label = "高" if speculation_points >= 70 else "中" if speculation_points >= 40 else "低"

        dimensions = {"quality": quality, "growth": growth, "annual_growth": annual_growth,
                      "revenue_growth": revenue_growth, "value": value,
                      "technical": technical, "chip": chip, "market": market,
                      "news": news, "liquidity": liquidity,
                      "durability": (evidence_durability if profile == "evidence_based"
                                     else durability),
                      "scale": scale, "business_quality": business_quality,
                      "cashflow_quality": cashflow_quality,
                      "growth_quality": growth_quality, "risk_resilience": risk_resilience,
                      "market_fit": market_fit}
        weights = PROFILE_WEIGHTS[profile]
        score = round(sum(dimensions[key] * weight / 100 for key, weight in weights.items()), 1)
        if profile == "evidence_based" and cycle_peak_risk:
            score = round(max(0, score - 7), 1)
        regime_gate = "normal"
        market_overheat = float(context.get("overheat_score", 0))
        if profile == "evidence_based" and market_overheat >= 70:
            regime_gate = "extreme_overheat"
            score = round(max(0, score - 6), 1)
        elif profile == "evidence_based" and market_overheat >= 45:
            regime_gate = "overheated"
            score = round(max(0, score - 3), 1)
        elif profile == "evidence_based" and market < 40:
            regime_gate = "risk_off"
            if min(business_quality, cashflow_quality, risk_resilience) < 50:
                continue
            score = round(score - 5, 1)
        elif profile == "evidence_based" and market >= 60:
            regime_gate = "risk_on"
            if growth_quality >= 65 and business_quality >= 50:
                score = round(min(100, score + 2), 1)
        evidence_decision = None
        invalidation_conditions = []
        if profile == "evidence_based":
            evidence_decision = ("優先研究" if score >= 75 else "可進一步研究"
                                 if score >= 65 else "觀察" if score >= 55 else "暫不推薦")
            if cashflow_quality < 50:
                invalidation_conditions.append("現金流品質低於門檻")
            if risk_resilience < 50:
                invalidation_conditions.append("財務韌性不足")
            if value < 30:
                invalidation_conditions.append("目前估值缺乏安全邊際")
            if market < 40:
                invalidation_conditions.append("市場處於防守狀態，須提高安全邊際")
            if cycle_peak_risk:
                invalidation_conditions.append("景氣循環高峰風險，需確認獲利不是一次性高點")
        reasons, risks = [], []
        labels = {"quality": "基本面品質", "revenue_growth": "營收成長", "value": "估值",
                  "technical": "技術趨勢", "chip": "法人籌碼", "liquidity": "市場關注度",
                  "durability": "獲利持續性", "scale": "企業規模與韌性"}
        for key in sorted(labels, key=lambda name: dimensions[name], reverse=True):
            if dimensions[key] >= 70:
                reasons.append(f"{labels[key]}優於多數同業（{dimensions[key]:.0f} 分）")
        if context.get("available") and market >= 60:
            reasons.append(f"大盤環境{context.get('regime')}（{market:.0f} 分）")
        for event in company_events[:2]:
            reasons.append(f"重大訊息：{event['title'][:42]}")
        if item["revenue_yoy"] is not None and item["revenue_yoy"] < 0: risks.append("月營收年增率為負")
        if item["roe"] is not None and item["roe"] <= 0: risks.append("ROE 為負")
        if item["debt_ratio"] is not None and item["debt_ratio"] > 70: risks.append("負債比超過 70%")
        if technical < 35: risks.append("近期價格趨勢偏弱")
        if market < 40: risks.append("整體市場環境偏空，系統性風險較高")
        if event_delta < 0: risks.append("近期重大訊息含風險關鍵字，需閱讀原文確認")
        if speculation_label == "高": risks.append("上漲高度依賴法人與量能，疑似籌碼推動，需防快速反轉")
        elif speculation_label == "中": risks.append("部分漲勢可能由法人買超與量能推動")
        item.update({
            "score": score, "rating": "優先研究" if score >= 75 else "值得追蹤" if score >= 60 else "觀察",
            "quality_score": round(quality, 1), "growth_score": round(growth, 1),
            "annual_growth_score": round(annual_growth, 1),
            "revenue_growth_score": round(revenue_growth, 1),
            "durability_score": round(evidence_durability if profile == "evidence_based"
                                      else durability, 1), "scale_score": round(scale, 1),
            "durability_coverage": durability_coverage,
            "financial_history_periods": history_periods,
            "profitable_years": int(item["profitable_years"] or 0),
            "dividend_years": int(item["dividend_years"] or 0),
            "annual_revenue_yoy": (round(item["annual_revenue_yoy"], 2)
                                   if item["annual_revenue_yoy"] is not None else None),
            "value_score": round(value, 1), "technical_score": round(technical, 1),
            "chip_score": round(chip, 1), "market_score": round(market, 1),
            "news_score": round(news, 1), "liquidity_score": round(liquidity, 1),
            "reasons": reasons[:4] or ["各項指標中性，列入觀察名單"], "risks": risks[:4],
            "market_regime": context.get("regime"), "context_as_of": context.get("as_of"),
            "event_count": len(company_events), "event_titles": [x["title"] for x in company_events[:3]],
            "institution_net_5d": round(institution_net_5d),
            "institution_net_ratio_5d": (round(institution_net_ratio, 2)
                                         if institution_net_ratio is not None else None),
            "institution_influence": influence_label,
            "speculation_risk": speculation_label,
            "institution_influence_reasons": influence_reasons[:4],
            "profile": profile, "method_version": "long-term-quality-v8",
            "business_quality_score": round(business_quality, 1),
            "cashflow_quality_score": round(cashflow_quality, 1),
            "growth_quality_score": round(growth_quality, 1),
            "risk_resilience_score": round(risk_resilience, 1),
            "evidence_ready": bool(item.get("evidence_ready")),
            "evidence_years": int(item.get("evidence_years") or 0),
            "cash_flow_periods": int(item.get("cash_flow_periods") or 0),
            "positive_fcf_ratio": item.get("positive_fcf_ratio"),
            "median_fcf_margin": item.get("median_fcf_margin"),
            "revenue_cagr_annual": item.get("revenue_cagr_annual"),
            "regime_gate": regime_gate,
            "market_overheat_score": market_overheat,
            "historical_value_score": item.get("historical_value_score"),
            "historical_valuation_observations": int(item.get("observations") or 0),
            "pe_cheapness_percentile": item.get("pe_cheapness_percentile"),
            "pb_cheapness_percentile": item.get("pb_cheapness_percentile"),
            "current_fcf_yield": item.get("current_fcf_yield"),
            "evidence_decision": evidence_decision,
            "invalidation_conditions": invalidation_conditions,
            "method_version": ("evidence-layered-v1" if profile == "evidence_based"
                               else "long-term-quality-v8"),
            "industry_category": item["industry_category"],
            "industry_model": item["industry_model"],
            "industry_adjustments": industry_adjustments,
            "cycle_peak_risk": cycle_peak_risk,
        })
        results.append(item)
    results.sort(key=lambda item: (item["score"], item["completeness"]), reverse=True)
    return results[:limit]
