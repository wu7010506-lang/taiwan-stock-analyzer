from __future__ import annotations

from datetime import date
from statistics import mean

from app.database import Database
from app.evidence_model import build_evidence_from_rows
from app.industry_model import industry_category, industry_label
from app.vnext_eligibility import assess_vnext_data_eligibility, normalized_date_sql


def _bounded(value: float | None, low: float, high: float, inverse: bool = False) -> float:
    if value is None or high <= low:
        return 50.0
    score = max(0.0, min(100.0, (value - low) / (high - low) * 100))
    return 100.0 - score if inverse else score


def _valuation_score(rows: list[dict]) -> tuple[float, int]:
    if not rows:
        return 50.0, 0
    latest = rows[-1]
    pe = latest.get("pe_ratio")
    pb = latest.get("pb_ratio")
    dividend_yield = latest.get("dividend_yield")
    absolute = (
        _bounded(pe, 8, 30, inverse=True) * .55
        + _bounded(pb, 1, 6, inverse=True) * .20
        + _bounded(dividend_yield, 0, 6) * .25
    )
    valid_pe = sorted(
        float(row["pe_ratio"])
        for row in rows
        if row.get("pe_ratio") is not None and float(row["pe_ratio"]) > 0
    )
    historical = 50.0
    if pe and len(valid_pe) >= 12:
        below = sum(value < float(pe) for value in valid_pe)
        historical = (1 - below / max(len(valid_pe) - 1, 1)) * 100
    return round(absolute * .6 + historical * .4, 1), len(valid_pe)


def _timing_score(prices: list[dict], context: dict) -> tuple[float, list[str]]:
    market_score = float(context.get("market_score", 50))
    overheat = float(context.get("overheat_score", 0))
    trend = 50.0
    if len(prices) >= 60:
        latest = float(prices[-1]["close"])
        ma20 = mean(float(row["close"]) for row in prices[-20:])
        ma60 = mean(float(row["close"]) for row in prices[-60:])
        trend = 70.0 if latest >= ma20 >= ma60 else 35.0 if latest < ma20 else 50.0
    score = market_score * .6 + trend * .4
    risks = []
    if overheat >= 70:
        score -= 25
        risks.append("market_extreme_overheat")
    elif overheat >= 45:
        score -= 12
        risks.append("market_overheat")
    if market_score < 40:
        risks.append("market_risk_off")
    return round(max(0, min(100, score)), 1), risks


def _evaluate_short_history_stock(
    database: Database, symbol: str, as_of_date: date, context: dict, eligibility: dict
) -> dict:
    """Conservative observation model for companies without five full years of history."""
    cutoff = as_of_date.isoformat()
    valuation_date = normalized_date_sql("valuation_date")
    with database.connect() as connection:
        financials = [dict(row) for row in connection.execute(
            """SELECT * FROM financial_snapshots WHERE symbol=? AND statement_date<=?
               ORDER BY statement_date DESC LIMIT 8""", (symbol, cutoff)
        )]
        prices = [dict(row) for row in connection.execute(
            """SELECT * FROM daily_prices WHERE symbol=? AND trade_date<=?
               ORDER BY trade_date DESC LIMIT 120""", (symbol, cutoff)
        )][::-1]
        valuations = [dict(row) for row in connection.execute(
            f"""SELECT * FROM valuations WHERE symbol=? AND {valuation_date}<=?
                 ORDER BY {valuation_date} DESC LIMIT 60""", (symbol, cutoff)
        )][::-1]
        revenue = connection.execute(
            """SELECT yoy_percent, cumulative_yoy_percent FROM monthly_revenues
               WHERE symbol=? AND revenue_month<=substr(?,1,7)
               ORDER BY revenue_month DESC LIMIT 1""", (symbol, cutoff)
        ).fetchone()

    if len(financials) < 4 or len(prices) < 60 or not valuations or not revenue:
        return {
            "model": "vnext", "symbol": symbol, "as_of_date": cutoff,
            "eligibility": eligibility, "value_score": None, "action": "insufficient_data",
            "confidence": "low", "company_quality": {}, "valuation_score": None,
            "timing_score": None, "supporting_reasons": [],
            "risks": [f"missing:{item}" for item in eligibility["missing"]],
        }

    profitable_ratio = sum(float(row.get("net_income") or 0) > 0 for row in financials) / len(financials)
    margins = [float(row["operating_income"] or 0) / float(row["revenue"] or 1) * 100
               for row in financials if row.get("revenue")]
    profitability = _bounded(mean(margins) if margins else None, 3, 20)
    revenue_growth = _bounded(float(revenue["yoy_percent"] or 0), 0, 30)
    valuation_score, _ = _valuation_score(valuations)
    timing_score, timing_risks = _timing_score(prices, context)
    quality_score = profitable_ratio * 100 * .45 + profitability * .35 + revenue_growth * .20
    value_score = round(quality_score * .65 + valuation_score * .35, 1)
    return {
        "model": "vnext_observation", "symbol": symbol, "as_of_date": cutoff,
        "eligibility": eligibility, "value_score": value_score, "action": "observation",
        "confidence": "low", "company_quality": {"score": round(quality_score, 1)},
        "valuation_score": valuation_score, "timing_score": timing_score,
        "crowding_risk": "unknown", "recommendation_suspended": False,
        "supporting_reasons": ["short_history_model", "recent_financials_available"],
        "risks": ["limited_operating_history", *timing_risks],
        "data_quality": {"financial_periods": len(financials), "price_periods": len(prices)},
    }


def evaluate_vnext_stock(
    database: Database,
    symbol: str,
    as_of_date: date,
    context: dict | None = None,
) -> dict:
    """Evaluate one stock without changing the existing recommendation model."""
    context = context or {}
    eligibility = assess_vnext_data_eligibility(database, symbol, as_of_date)
    if not eligibility["formal_recommendation_allowed"]:
        if eligibility["status"] == "observation":
            return _evaluate_short_history_stock(database, symbol, as_of_date, context, eligibility)
        return {
            "model": "vnext", "symbol": symbol, "as_of_date": as_of_date.isoformat(),
            "eligibility": eligibility, "value_score": None, "action": "insufficient_data",
            "confidence": "low", "company_quality": {}, "valuation_score": None,
            "timing_score": None, "supporting_reasons": [],
            "risks": [f"missing:{item}" for item in eligibility["missing"]],
        }

    cutoff = as_of_date.isoformat()
    valuation_date = normalized_date_sql("valuation_date")
    with database.connect() as connection:
        instrument_row = connection.execute(
            "SELECT * FROM instruments WHERE symbol=?", (symbol,)
        ).fetchone()
        financial_rows = [dict(row) for row in connection.execute(
            """SELECT * FROM financial_snapshots
               WHERE symbol=? AND statement_date<=?
               ORDER BY fiscal_year, fiscal_quarter""",
            (symbol, cutoff),
        )]
        valuation_rows = [dict(row) for row in connection.execute(
            f"""SELECT *, {valuation_date} AS normalized_valuation_date
               FROM valuations WHERE symbol=? AND {valuation_date}<=?
               ORDER BY {valuation_date}""",
            (symbol, cutoff),
        )]
        prices = [dict(row) for row in connection.execute(
            """SELECT * FROM daily_prices WHERE symbol=? AND trade_date<=?
               ORDER BY trade_date DESC LIMIT 250""",
            (symbol, cutoff),
        )][::-1]
        institution_rows = [dict(row) for row in connection.execute(
            """SELECT * FROM institutional_trades WHERE symbol=? AND trade_date<=?
               ORDER BY trade_date DESC LIMIT 5""",
            (symbol, cutoff),
        )]

    evidence = build_evidence_from_rows(financial_rows)[symbol]
    category = industry_category(instrument_row["industry"] if instrument_row else None)
    capital_returns = _bounded(evidence.get("median_roe_annual"), 5, 25)
    profitability = _bounded(evidence.get("median_operating_margin"), 5, 25)
    cashflow_quality = (
        _bounded(evidence.get("positive_fcf_ratio"), .4, 1) * .4
        + _bounded(evidence.get("cash_conversion"), .5, 1.2) * .3
        + _bounded(evidence.get("median_fcf_margin"), 0, 15) * .3
    )
    durability = (
        _bounded(evidence.get("profitable_year_ratio"), .5, 1) * .5
        + _bounded(evidence.get("positive_eps_year_ratio"), .5, 1) * .5
    )
    financial_safety = _bounded(evidence.get("latest_debt_ratio"), 20, 80, inverse=True)
    if category == "financial":
        quality_score = capital_returns * .5 + durability * .3 + financial_safety * .2
        cashflow_quality = 50.0
    else:
        quality_score = (
            capital_returns * .30 + profitability * .20 + cashflow_quality * .25
            + durability * .15 + financial_safety * .10
        )
    valuation_score, valuation_samples = _valuation_score(valuation_rows)
    value_score = round(quality_score * .7 + valuation_score * .3, 1)
    timing_score, timing_risks = _timing_score(prices, context)
    recent_prices = prices[-5:]
    recent_volume = sum(float(row["volume"] or 0) for row in recent_prices)
    institution_net = sum(
        float(row.get("foreign_net") or 0) + float(row.get("trust_net") or 0)
        for row in institution_rows
    )
    institution_ratio = institution_net / recent_volume * 100 if recent_volume else None
    price_change_5d = None
    if len(recent_prices) >= 5 and float(recent_prices[0]["close"]):
        price_change_5d = (
            float(recent_prices[-1]["close"]) / float(recent_prices[0]["close"]) - 1
        ) * 100
    if (institution_ratio is not None and institution_ratio >= 15
            and price_change_5d is not None and price_change_5d >= 8):
        crowding_risk = "high"
    elif institution_ratio is not None and institution_ratio >= 5:
        crowding_risk = "medium"
    else:
        crowding_risk = "low"

    if value_score >= 75 and timing_score >= 55:
        action = "buy"
    elif value_score >= 70:
        action = "accumulate" if timing_score >= 45 else "wait"
    elif value_score >= 60:
        action = "hold"
    elif value_score >= 45:
        action = "reduce"
    else:
        action = "sell"
    if crowding_risk == "high" and action in {"buy", "accumulate"}:
        action = "wait"

    company_events = [
        event for event in context.get("events", []) if event.get("symbol") == symbol
    ]
    material_negative_events = [
        event for event in company_events
        if event.get("verified") is True
        and event.get("materiality") == "high"
        and float(event.get("sentiment", 0)) < 0
    ]
    recommendation_suspended = bool(material_negative_events)
    if recommendation_suspended:
        action = "wait"

    confidence = "high" if valuation_samples >= 36 else "medium"
    reasons = []
    if quality_score >= 70:
        reasons.append("durable_business_quality")
    if cashflow_quality >= 70 and category != "financial":
        reasons.append("cashflow_supports_earnings")
    if valuation_score >= 60:
        reasons.append("valuation_has_margin_of_safety")
    risks = list(timing_risks)
    if crowding_risk == "high":
        risks.append("institution_driven_surge")
    if recommendation_suspended:
        risks.append("verified_material_negative_event")
    if valuation_samples < 12:
        risks.append("limited_valuation_history")
    return {
        "model": "vnext", "symbol": symbol, "name": instrument_row["name"],
        "industry": instrument_row["industry"], "industry_category": category,
        "industry_model": industry_label(instrument_row["industry"]),
        "as_of_date": cutoff, "eligibility": eligibility,
        "value_score": value_score, "action": action, "confidence": confidence,
        "company_quality": {
            "score": round(quality_score, 1), "capital_returns": round(capital_returns, 1),
            "profitability": round(profitability, 1),
            "cashflow_quality": round(cashflow_quality, 1),
            "durability": round(durability, 1),
            "financial_safety": round(financial_safety, 1),
        },
        "valuation_score": valuation_score, "timing_score": timing_score,
        "crowding_risk": crowding_risk,
        "institution_net_ratio_5d": (
            round(institution_ratio, 2) if institution_ratio is not None else None
        ),
        "price_change_5d": round(price_change_5d, 2) if price_change_5d is not None else None,
        "recommendation_suspended": recommendation_suspended,
        "event_assessment": {
            "verified_events": sum(event.get("verified") is True for event in company_events),
            "material_negative_events": len(material_negative_events),
            "score_adjustment": 0,
        },
        "supporting_reasons": reasons, "risks": risks,
        "change_conditions": ["fundamentals_deteriorate", "valuation_overheats",
                              "market_regime_changes"],
    }


def recommend_vnext_stocks(
    database: Database,
    as_of_date: date,
    context: dict | None = None,
    limit: int = 20,
) -> dict:
    """Build a vNext list with market cash and concentration constraints."""
    context = context or {}
    market_score = float(context.get("market_score", 50))
    overheat = float(context.get("overheat_score", 0))
    if market_score < 40 or overheat >= 70:
        cash_target = 60
    elif overheat >= 45:
        cash_target = 40
    elif market_score >= 60:
        cash_target = 20
    else:
        cash_target = 30

    with database.connect() as connection:
        symbols = [row[0] for row in connection.execute(
            "SELECT symbol FROM instruments ORDER BY symbol"
        )]
    candidates = []
    status_counts = {"eligible": 0, "observation": 0, "insufficient_data": 0}
    missing_counts: dict[str, int] = {}
    for symbol in symbols:
        result = evaluate_vnext_stock(database, symbol, as_of_date, context)
        status = result["eligibility"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        for missing in result["eligibility"]["missing"]:
            missing_counts[missing] = missing_counts.get(missing, 0) + 1
        if (result["value_score"] is not None and result["value_score"] >= 60
                and not result.get("recommendation_suspended", False)):
            candidates.append(result)
    candidates.sort(key=lambda item: (item["value_score"], item["timing_score"]), reverse=True)

    sector_used: dict[str, float] = {}
    recommendations = []
    exposure_factor = (100 - cash_target) / 80
    for candidate in candidates:
        if len(recommendations) >= limit:
            break
        score = candidate["value_score"]
        base_position = 10.0 if score >= 75 else 7.0 if score >= 65 else 5.0
        position = round(base_position * exposure_factor, 1)
        sector = candidate.get("industry") or "unknown"
        remaining = max(0.0, 25.0 - sector_used.get(sector, 0.0))
        position = min(position, 10.0, remaining)
        if position <= 0:
            continue
        sector_used[sector] = sector_used.get(sector, 0.0) + position
        recommendations.append({
            **candidate,
            "rank": len(recommendations) + 1,
            "suggested_position_percent": position,
        })
    return {
        "model": "vnext",
        "as_of_date": as_of_date.isoformat(),
        "market_regime": context.get("regime", "unknown"),
        "cash_target_percent": cash_target,
        "single_stock_limit_percent": 10,
        "sector_limits_percent": 25,
        "universe_summary": {"evaluated": len(symbols), **status_counts},
        "missing_summary": missing_counts,
        "recommendations": recommendations,
    }
