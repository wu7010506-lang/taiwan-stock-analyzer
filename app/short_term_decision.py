from __future__ import annotations

"""Research-only 3–10 session short-term decision engine.

Fundamentals are a safety gate here, not a ranking score.  The two entry
setups deliberately remain fixed research rules: trend breakout and range
mean reversion.  They must not be treated as a validated profit claim.
"""

from datetime import date, timedelta
from collections import Counter
from statistics import median

from app.database import Database
from app.point_in_time import financial_available_sql
from app.short_term_trade import build_breakout_trade_plan
from app.short_term_fundamentals import (
    HIGH_PE_REVIEW_THRESHOLD,
    MAX_PE_RATIO,
    MIN_CORE_EARNINGS_RATIO_PERCENT,
    MIN_HIGH_PE_REVENUE_YOY_PERCENT,
    MIN_REVENUE_YOY_PERCENT,
    load_short_term_fundamental_assessment,
)
from app.technical_indicators import calculate_technical_indicators


MIN_AVERAGE_DAILY_TURNOVER = 5_000_000
MIN_INDUSTRY_PEERS = 3
STRATEGY_VERSION = "short-term-3-10d-v2.5-pit-evidence"


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _iso_date(value: object) -> str | None:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) == 7 and text.isdigit():
        return f"{int(text[:3]) + 1911:04d}-{text[3:5]}-{text[5:]}"
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 3 and all(part.isdigit() for part in parts):
        text = f"{int(parts[0]) + 1911:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def market_mode(context: dict) -> str:
    score = _number(context.get("market_score"))
    change_20 = _number(context.get("index_change_20d"))
    if score is None:
        return "unavailable"
    if score < 40:
        # Historical validation found positive average forward returns even
        # below 40, but materially worse adverse paths.  Treat this as a
        # position-risk state, not a categorical prediction of lower prices.
        return "defensive"
    if (change_20 or 0) >= 0 and score >= 55:
        return "trend"
    return "range"


def _candidate_universe(
    database: Database,
    as_of_date: date,
    *,
    end_of_day_data_cutoff: str | None = None,
) -> list[dict]:
    """Return liquid stocks with enough point-in-time data to assess fundamentals."""
    cutoff = as_of_date.isoformat()
    financial_available_date = financial_available_sql("statement_date")
    with database.connect() as connection:
        rows = connection.execute(
            f"""WITH price_base AS (
                   SELECT symbol, market, trade_date, close, volume,
                          ROW_NUMBER() OVER (
                              PARTITION BY symbol, market ORDER BY trade_date DESC
                          ) AS recent_rank,
                          COUNT(*) OVER (PARTITION BY symbol, market) AS price_periods
                   FROM daily_prices WHERE trade_date<=?
               ), price_summary AS (
                   SELECT symbol, market,
                          MAX(CASE WHEN recent_rank=1 THEN trade_date END) AS latest_price_date,
                          MAX(CASE WHEN recent_rank=1 THEN close END) AS close,
                          MAX(price_periods) AS price_periods,
                          AVG(CASE WHEN recent_rank<=20 THEN close*volume END) AS average_turnover_20
                   FROM price_base GROUP BY symbol, market
               ), financial_base AS (
                   SELECT fs.symbol, fs.market, statement_date, {financial_available_date} AS available_date,
                          total_assets, total_liabilities,
                          net_income, free_cash_flow,
                          ROW_NUMBER() OVER (
                              PARTITION BY fs.symbol, fs.market ORDER BY {financial_available_date} DESC,
                              fiscal_year DESC, fiscal_quarter DESC
                          ) AS recent_rank,
                          COUNT(*) OVER (PARTITION BY fs.symbol, fs.market) AS financial_periods
                   FROM financial_snapshots fs
                   JOIN price_summary ps ON ps.symbol=fs.symbol AND ps.market=fs.market
                   WHERE statement_date IS NOT NULL
                     AND {financial_available_date}<=ps.latest_price_date
               ), financial_summary AS (
                   SELECT symbol, market,
                          MAX(CASE WHEN recent_rank=1 THEN statement_date END) AS latest_financial_date,
                          MAX(CASE WHEN recent_rank=1 THEN available_date END) AS latest_financial_available_date,
                          MAX(CASE WHEN recent_rank=1 THEN total_assets END) AS total_assets,
                          MAX(CASE WHEN recent_rank=1 THEN total_liabilities END) AS total_liabilities,
                          MAX(CASE WHEN recent_rank=1 THEN net_income END) AS net_income,
                          MAX(CASE WHEN recent_rank=1 THEN free_cash_flow END) AS free_cash_flow,
                          MAX(financial_periods) AS financial_periods
                   FROM financial_base GROUP BY symbol, market
               ), valuation_base AS (
                   SELECT v.symbol, v.market, valuation_date, pe_ratio,
                          ROW_NUMBER() OVER (
                              PARTITION BY v.symbol, v.market ORDER BY valuation_date DESC
                          ) AS recent_rank
                   FROM valuations v
                   JOIN price_summary ps ON ps.symbol=v.symbol AND ps.market=v.market
                   WHERE date(CASE WHEN length(valuation_date)=8
                              THEN substr(valuation_date,1,4)||'-'||substr(valuation_date,5,2)||'-'||substr(valuation_date,7,2)
                              ELSE valuation_date END)<=date(?)
               ), valuation_summary AS (
                   SELECT symbol, market,
                          MAX(CASE WHEN recent_rank=1 THEN valuation_date END) AS latest_valuation_date,
                          MAX(CASE WHEN recent_rank=1 THEN pe_ratio END) AS pe_ratio
                   FROM valuation_base GROUP BY symbol, market
               ), revenue_base AS (
                   SELECT r.symbol, r.market, revenue_month, yoy_percent,
                          date(revenue_month||'-01','+1 month','+9 days') AS available_date,
                          ROW_NUMBER() OVER (
                              PARTITION BY r.symbol, r.market ORDER BY revenue_month DESC
                          ) AS recent_rank
                   FROM monthly_revenues r
                   JOIN price_summary ps ON ps.symbol=r.symbol AND ps.market=r.market
                   WHERE date(revenue_month||'-01','+1 month','+9 days')<=date(ps.latest_price_date)
               ), revenue_summary AS (
                   SELECT symbol, market,
                          MAX(CASE WHEN recent_rank=1 THEN revenue_month END) AS latest_revenue_month,
                          MAX(CASE WHEN recent_rank=1 THEN available_date END) AS latest_revenue_available_date,
                          MAX(CASE WHEN recent_rank=1 THEN yoy_percent END) AS latest_revenue_yoy_percent
                   FROM revenue_base GROUP BY symbol, market
               )
               SELECT i.symbol, i.market, i.name, i.industry, p.latest_price_date, p.close,
                      p.price_periods, p.average_turnover_20, f.latest_financial_date,
                      f.latest_financial_available_date,
                      f.financial_periods, f.total_assets, f.total_liabilities,
                      f.net_income, f.free_cash_flow,
                      v.latest_valuation_date, v.pe_ratio,
                      r.latest_revenue_month, r.latest_revenue_available_date,
                      r.latest_revenue_yoy_percent
               FROM instruments i
               JOIN price_summary p ON p.symbol=i.symbol AND p.market=i.market
               JOIN financial_summary f ON f.symbol=i.symbol AND f.market=i.market
               JOIN valuation_summary v ON v.symbol=i.symbol AND v.market=i.market
               JOIN revenue_summary r ON r.symbol=i.symbol AND r.market=i.market
               WHERE date(p.latest_price_date)>=date(?, '-7 days')
                 AND date(f.latest_financial_available_date)>=date(p.latest_price_date, '-190 days')
                 AND p.price_periods>=60 AND f.financial_periods>=4
                 AND p.average_turnover_20>=?
                 AND f.total_assets>0
               ORDER BY p.average_turnover_20 DESC""",
            (cutoff, end_of_day_data_cutoff or cutoff, cutoff,
             MIN_AVERAGE_DAILY_TURNOVER),
        ).fetchall()
    return [dict(row) for row in rows]


def _evaluated_candidates(
    database: Database,
    as_of_date: date,
    *,
    end_of_day_data_cutoff: str | None = None,
) -> tuple[list[dict], list[dict]]:
    passed, rejected = [], []
    universe = (
        _candidate_universe(
            database, as_of_date, end_of_day_data_cutoff=end_of_day_data_cutoff
        )
        if end_of_day_data_cutoff
        else _candidate_universe(database, as_of_date)
    )
    for row in universe:
        assessment_args = (
            database, str(row["symbol"]), str(row["market"]),
            str(row["latest_price_date"]), float(row["close"]),
        )
        assessment = (
            load_short_term_fundamental_assessment(
                *assessment_args, end_of_day_data_cutoff=end_of_day_data_cutoff
            )
            if end_of_day_data_cutoff
            else load_short_term_fundamental_assessment(*assessment_args)
        )
        evaluated = {
            **row,
            "pe_ratio": assessment.get("pe_ratio"),
            "fundamental_assessment": assessment,
        }
        (passed if assessment["passed"] else rejected).append(evaluated)
    return passed, rejected


def _base_candidates(database: Database, as_of_date: date) -> list[dict]:
    """Return only stocks that pass the shared point-in-time safety gate."""
    passed, _ = _evaluated_candidates(database, as_of_date)
    return passed


def short_term_fundamental_candidates(database: Database, as_of_date: date) -> list[dict]:
    """Public, point-in-time short-term safety gate for paper/research runners."""
    return _base_candidates(database, as_of_date)


def _institutional_summary(trades: list[dict], prices: list[dict]) -> dict:
    recent = trades[-5:]
    volume = sum(_number(row.get("volume")) or 0 for row in prices[-5:])
    foreign = sum(_number(row.get("foreign_net")) or 0 for row in recent)
    trust = sum(_number(row.get("trust_net")) or 0 for row in recent)
    foreign_ratio = round(foreign / volume * 100, 4) if volume else None
    trust_ratio = round(trust / volume * 100, 4) if volume else None
    return {
        "as_of": recent[-1].get("trade_date") if recent else None,
        "foreign_net_5d": round(foreign, 2) if recent else None,
        "trust_net_5d": round(trust, 2) if recent else None,
        "foreign_net_to_volume_5d_percent": foreign_ratio,
        "trust_net_to_volume_5d_percent": trust_ratio,
        "foreign_signal": "偏買" if foreign_ratio is not None and foreign_ratio > 0 else "偏賣" if foreign_ratio is not None and foreign_ratio < 0 else "中性或不足",
        "trust_signal": "偏買" if trust_ratio is not None and trust_ratio > 0 else "偏賣" if trust_ratio is not None and trust_ratio < 0 else "中性或不足",
        "available": bool(recent),
    }


def _event_risk(row: dict, market_context: dict, dividend_events: list[dict], as_of_date: date) -> dict:
    company_events = [event for event in market_context.get("events", [])
                      if str(event.get("symbol")) == str(row.get("symbol"))]
    hard_reasons = []
    if any(event.get("verified") is True and event.get("materiality") == "high"
           and (_number(event.get("sentiment")) or 0) < 0 for event in company_events):
        hard_reasons.append("存在已確認的重大負面事件。")
    upcoming = []
    for event in dividend_events:
        try:
            ex_date = date.fromisoformat(str(event.get("ex_date")))
        except ValueError:
            continue
        if as_of_date < ex_date <= as_of_date + timedelta(days=14):
            upcoming.append(event)
    if upcoming:
        hard_reasons.append("未來 14 日內有除權息，價格將機械調整，現有突破價與停損不可直接使用。")
    return {
        "hard_blockers": hard_reasons,
        "official_event_titles": [str(event.get("title")) for event in company_events[:3]],
        "upcoming_dividend_dates": [event.get("ex_date") for event in upcoming],
        "limitations": "目前有重大訊息與除權息資料；處置、注意、暫停交易名單尚未接入，開盤前仍須人工確認。",
    }


def _decision_for_candidate(row: dict, prices: list[dict], market_context: dict,
                            technical: dict | None = None,
                            industry_context: dict | None = None,
                            institutional_trades: list[dict] | None = None,
                            dividend_events: list[dict] | None = None,
                            as_of_date: date | None = None) -> dict:
    technical = technical or calculate_technical_indicators(prices)
    indicators = technical["indicators"]
    mode = market_mode(market_context)
    trade_plan = build_breakout_trade_plan(
        prices, indicators, mode, _number(row.get("average_turnover_20"))
    )
    market_5 = _number(market_context.get("index_change_5d"))
    market_20 = _number(market_context.get("index_change_20d"))
    return_5 = _number(indicators.get("return_5d_percent"))
    return_10 = _number(indicators.get("return_10d_percent"))
    return_20 = _number(indicators.get("return_20d_percent"))
    industry_context = industry_context or {}
    relative_market_5 = return_5 - market_5 if return_5 is not None and market_5 is not None else None
    relative_market_20 = return_20 - market_20 if return_20 is not None and market_20 is not None else None
    industry_5 = _number(industry_context.get("return_5d_percent"))
    industry_10 = _number(industry_context.get("return_10d_percent"))
    relative_industry_5 = return_5 - industry_5 if return_5 is not None and industry_5 is not None else None
    relative_industry_10 = return_10 - industry_10 if return_10 is not None and industry_10 is not None else None
    flow = _institutional_summary(institutional_trades or [], prices)
    event = _event_risk(row, market_context, dividend_events or [], as_of_date or date.today())
    if event["hard_blockers"]:
        trade_plan.setdefault("blocking_reasons", []).extend(event["hard_blockers"])
        trade_plan["event_blocking_reasons"] = event["hard_blockers"]

    market_data_ready = market_context.get("data_aligned_to_signal", True)
    data_quality_blockers = []
    if not market_data_ready:
        data_quality_blockers.append("大盤資料與個股訊號日不一致，不能套用市場狀態與動態 RR／量能門檻。")
        trade_plan.setdefault("blocking_reasons", []).extend(data_quality_blockers)

    core = trade_plan.get("core_blocking_reasons", [])
    cost_rr = _number(trade_plan.get("cost_adjusted_risk_reward"))
    required_rr = _number(trade_plan.get("required_rr"))
    analysis_pass = not core
    rr_pass = cost_rr is not None and required_rr is not None and cost_rr >= required_rr
    if analysis_pass and event["hard_blockers"]:
        action, setup = "no_trade", "event_blocked"
        reason = "技術條件雖成立，但重大事件或除權息使現有價格計畫失效。"
    elif analysis_pass and data_quality_blockers:
        action, setup = "no_trade", "data_not_aligned"
        reason = "技術條件雖成立，但市場資料日期未對齊，不能套用動態交易門檻。"
    elif analysis_pass and not rr_pass:
        action, setup = "no_trade", "confirmed_breakout_rr_insufficient"
        reason = "突破、趨勢與量能成立，但獨立目標的成本後風險報酬比不足。"
    elif analysis_pass and rr_pass:
        action, setup = "analysis_pass", "confirmed_breakout"
        reason = "突破、趨勢、成交量、ATR 風控與獨立目標的成本後 RR 均符合；策略治理仍限制為紙上觀察。"
    elif indicators.get("trend_confirmation"):
        action, setup = "wait_breakout", "trend_breakout"
        reason = "中期趨勢成立，等待收盤突破、量能與成本後 RR 同時確認。"
    else:
        action, setup = "no_trade", "none"
        reason = "價格結構尚未符合固定的 3–10 日突破策略。"

    natr = _number(indicators.get("natr_14"))
    base_position_cap = 2.5 if mode == "defensive" else 5.0
    volatility_scale = 0.5 if natr is not None and natr >= 7 else 0.75 if natr is not None and natr >= 5 else 1.0

    fields = ("symbol", "market", "name", "industry", "close", "latest_price_date",
              "latest_financial_date", "latest_financial_available_date", "average_turnover_20",
              "latest_valuation_date", "pe_ratio", "latest_revenue_month",
              "latest_revenue_available_date", "latest_revenue_yoy_percent")
    return {
        **{key: row.get(key) for key in fields},
        "action": action, "setup": setup, "reason": reason, "market_mode": mode,
        "holding_sessions": "3–10", "execution": "訊號日收盤後判定；下一交易日以實際開盤價重算成本後 RR",
        "invalidation_price": trade_plan.get("stop"), "trade_plan": trade_plan,
        "market_position_cap_percent": base_position_cap,
        "paper_position_cap_percent": round(base_position_cap * volatility_scale, 2),
        "position_sizing_basis": "市場部位上限 × NATR 波動縮放；NATR≥5% 乘 0.75，NATR≥7% 乘 0.5",
        "max_new_position_percent": 0,
        "fundamental_snapshot": row.get("fundamental_assessment") or {
            "passed": True,
            "pe_ratio": _number(row.get("pe_ratio")), "pe_ceiling": MAX_PE_RATIO,
            "revenue_yoy_percent": _number(row.get("latest_revenue_yoy_percent")),
            "revenue_yoy_floor": MIN_REVENUE_YOY_PERCENT,
            "valuation_source_date": row.get("latest_valuation_date"),
            "revenue_month": row.get("latest_revenue_month"),
            "blocking_reasons": [],
        },
        "indicators": {
            key: indicators.get(key) for key in (
                "sma_5", "sma_10", "sma_20", "sma_60", "return_1d_percent",
                "return_5d_percent", "return_10d_percent", "return_20d_percent",
                "volume_ratio_5", "volume_ratio_20", "rsi_14", "macd", "macd_signal",
                "macd_histogram", "macd_histogram_change", "atr_14", "natr_14", "mfi_14",
                "adx_14", "latest_gap_percent", "latest_range_percent",
            )
        } | {
            "relative_market_5d_percent": relative_market_5,
            "relative_market_20d_percent": relative_market_20,
            "relative_industry_5d_percent": relative_industry_5,
            "relative_industry_10d_percent": relative_industry_10,
        },
        "industry_context": industry_context,
        "institutional_flow": flow,
        "event_risk": event,
        "data_quality_blockers": data_quality_blockers,
        "data_as_of": {
            "price": row.get("latest_price_date"),
            "financial_available": row.get("latest_financial_available_date"),
            "valuation": row.get("latest_valuation_date"),
            "revenue": row.get("latest_revenue_month"),
            "institutional": flow.get("as_of"),
        },
        "limitations": [
            "基本面僅作安全門檻，不代表短線一定上漲。",
            "產業強度以通過安全門檻的同產業股票中位數估計，不等於完整產業指數。",
            "策略仍未完成足夠樣本外與紙上驗證；分析通過不等於允許正式交易。",
        ],
    }


def _research_priority_score(decision: dict) -> tuple[int, list[str], list[str], dict]:
    """Rank attention quality without using today's trigger or provisional RR."""
    indicators = decision.get("indicators", {})
    plan = decision.get("trade_plan", {})
    evidence, risks = [], []
    components = {"trend": 0, "relative_strength": 0, "liquidity": 0,
                  "institutional_confirmation": 0, "risk_penalty": 0}

    # Trend (35): this is stock quality for a short-term watchlist, not an entry.
    sma5, sma10, sma20, sma60 = (_number(indicators.get(key))
                                for key in ("sma_5", "sma_10", "sma_20", "sma_60"))
    if all(value is not None for value in (sma5, sma10, sma20, sma60)) and sma5 >= sma10 >= sma20 >= sma60:
        components["trend"] = 35
        evidence.append("短中期均線方向一致")
    elif sma20 is not None and sma60 is not None and sma20 >= sma60:
        components["trend"] = 20
        evidence.append("中期趨勢偏多")
    else:
        risks.append("均線結構尚未形成短中期一致多頭")

    # Relative strength (35): residual market and peer performance, not raw return.
    relative_20 = _number(indicators.get("relative_market_20d_percent"))
    if relative_20 is not None and relative_20 > 0:
        components["relative_strength"] += min(20, 10 + max(0, round(relative_20)))
        evidence.append("20 日表現優於大盤")
    elif relative_20 is not None:
        risks.append("20 日表現落後大盤")

    relative_industry = [_number(indicators.get(key)) for key in
                         ("relative_industry_5d_percent", "relative_industry_10d_percent")]
    relative_industry = [value for value in relative_industry if value is not None]
    if relative_industry:
        average_relative = sum(relative_industry) / len(relative_industry)
        if average_relative > 0:
            components["relative_strength"] += min(15, 8 + max(0, round(average_relative)))
            evidence.append("近期表現優於足量同產業樣本")

    # Liquidity (20): all candidates passed the minimum; deeper liquidity ranks higher.
    turnover = _number(decision.get("average_turnover_20"))
    if turnover is not None:
        components["liquidity"] = 20 if turnover >= 100_000_000 else 15 if turnover >= 30_000_000 else 10 if turnover >= 10_000_000 else 5

    # Institutional flows are separate confirmations; opposite flows never cancel.
    flow = decision.get("institutional_flow", {})
    foreign_ratio = _number(flow.get("foreign_net_to_volume_5d_percent"))
    trust_ratio = _number(flow.get("trust_net_to_volume_5d_percent"))
    if foreign_ratio is not None and foreign_ratio > 0:
        components["institutional_confirmation"] += 5
        evidence.append("外資近 5 日偏買超")
    elif foreign_ratio is not None and foreign_ratio < 0:
        risks.append("外資近 5 日偏賣超")
    if trust_ratio is not None and trust_ratio > 0:
        components["institutional_confirmation"] += 5
        evidence.append("投信近 5 日偏買超")
    elif trust_ratio is not None and trust_ratio < 0:
        risks.append("投信近 5 日偏賣超")
    if foreign_ratio is None and trust_ratio is None:
        risks.append("法人資料不足，不加分也不補中性分")

    components["risk_penalty"] = -min(12, len(plan.get("soft_risks", [])) * 4)
    risks.extend(plan.get("soft_risks", []))
    if decision.get("event_risk", {}).get("hard_blockers"):
        components["risk_penalty"] -= 25
        risks.extend(decision["event_risk"]["hard_blockers"])
    if decision.get("market_mode") == "defensive":
        risks.append("大盤處於防守狀態，僅適合降低曝險的觀察")
    score = sum(components.values())
    return max(0, min(score, 100)), evidence[:6], risks[:6], components


def _attention_grade(score: int, decision: dict) -> str:
    """Absolute watch priority among stocks that already passed fundamentals."""
    if decision.get("event_risk", {}).get("hard_blockers") or decision.get("data_quality_blockers"):
        return "D"
    if score >= 65:
        return "A"
    if score >= 45:
        return "B"
    return "C"


def _execution_status(decision: dict) -> tuple[str, str]:
    """Evaluate today's breakout operation independently from attention quality."""
    plan = decision.get("trade_plan", {})
    fundamental = decision.get("fundamental_snapshot") or {}
    if fundamental.get("passed") is False:
        return "blocked_fundamental", "基本面安全門檻未通過；技術觸發不能覆蓋估值或獲利品質風險"
    if decision.get("event_risk", {}).get("hard_blockers"):
        return "blocked", "重大事件或除權息使目前交易計畫失效"
    if decision.get("data_quality_blockers"):
        return "blocked", "市場與個股資料日期未對齊"
    core = plan.get("core_blocking_reasons", [])
    if core:
        return "waiting_trigger", "等待收盤突破、趨勢與市場要求量能完成"
    market_access = plan.get("trigger_checks", {}).get("market_access", {})
    if market_access and not market_access.get("passed"):
        return "blocked", "訊號日接近漲停，須等次日實際開盤確認可成交性"
    chase_control = plan.get("trigger_checks", {}).get("chase_control", {})
    if chase_control and not chase_control.get("passed"):
        return "blocked_overextended", "突破成立，但短線漲幅與均線乖離過大；等待整理後再評估，不追價"
    cost_rr, required_rr = (_number(plan.get(key)) for key in
                            ("cost_adjusted_risk_reward", "required_rr"))
    if cost_rr is None or required_rr is None or cost_rr < required_rr:
        return "reject_rr", "技術觸發完成，但獨立目標的成本後 RR 不足"
    if plan.get("soft_risks"):
        return "ready_with_risk", "操作條件完成，但須降低部位並留意過熱或波動風險"
    return "ready", "突破、量能、ATR 與獨立目標的成本後 RR 均完成"


def _operation_gap(decision: dict) -> dict:
    """Describe what remains without treating provisional RR as a signal."""
    plan = decision.get("trade_plan", {})
    checks = plan.get("trigger_checks", {})
    status = decision.get("operation_status")
    missing = []
    if status == "waiting_trigger":
        for key in ("breakout", "trend", "volume", "atr_risk"):
            check = checks.get(key, {})
            if check and not check.get("passed"):
                missing.append({"key": key, **check})
    elif status == "reject_rr":
        check = checks.get("risk_reward", {})
        missing.append({"key": "risk_reward", **check})
    elif status == "blocked":
        check = checks.get("market_access", {})
        if check and not check.get("passed"):
            missing.append({"key": "market_access", **check})
    return {
        "missing_count": len(missing),
        "missing_checks": missing,
        "breakout_gap_percent": checks.get("breakout", {}).get("gap_percent"),
        "volume_gap_percent": checks.get("volume", {}).get("gap_percent"),
        "rr_is_provisional": checks.get("risk_reward", {}).get("provisional", True),
    }


def _compact_tracking_status(decision: dict) -> dict:
    plan = decision.get("trade_plan") or {}
    return {
        "symbol": decision.get("symbol"),
        "market": decision.get("market"),
        "name": decision.get("name"),
        "close": decision.get("close"),
        "latest_price_date": decision.get("latest_price_date"),
        "operation_status": decision.get("operation_status"),
        "operation_reason": decision.get("operation_reason"),
        "attention_score": decision.get("attention_score"),
        "operation_gap": decision.get("operation_gap") or {},
        "trigger_checks": plan.get("trigger_checks") or {},
    }


def _closest_operation_sort_key(decision: dict) -> tuple:
    """Rank how close a watched stock is to a valid trigger.

    A price already above the breakout level has no remaining breakout gap;
    it must not gain priority merely because its raw distance is more negative.
    Single-condition gaps are ordered by how directly they can be confirmed on
    the next session: volume, breakout, trend, then ATR risk.
    """
    gap = decision.get("operation_gap", {})
    missing_keys = {
        check.get("key") for check in gap.get("missing_checks", [])
        if check.get("key")
    }
    single_condition_priority = {
        "volume": 0,
        "breakout": 1,
        "trend": 2,
        "atr_risk": 3,
    }
    condition_priority = (
        single_condition_priority.get(next(iter(missing_keys)), 4)
        if len(missing_keys) == 1 else 4
    )
    if "breakout" in missing_keys:
        relevant_gap = _number(gap.get("breakout_gap_percent"))
    elif "volume" in missing_keys:
        relevant_gap = _number(gap.get("volume_gap_percent"))
    else:
        relevant_gap = 0
    remaining_gap = max(relevant_gap or 0, 0)
    return (
        gap.get("missing_count", 99),
        condition_priority,
        remaining_gap,
        -decision["attention_score"],
        -float(decision["average_turnover_20"]),
    )


def assess_short_term_position(row: dict, prices: list[dict], as_of_date: date) -> dict:
    """Give a deterministic 3–10 session decision for a recorded short position."""
    current_close = _number(row.get("close"))
    purchase_date = str(row.get("purchase_date") or "")
    sessions_held = sum(1 for price in prices if price.get("trade_date", "") >= purchase_date)
    base = {"source": "short_term_research", "new_allocation_percent": 0,
            "holding_sessions": sessions_held, "execution": "以今日收盤檢查；若觸發，下一交易日開盤執行",
            "research_only": True}
    if current_close is None:
        return {**base, "action": "hold", "reasons": [], "risks": ["missing_current_price"]}
    stop, target = _number(row.get("stop_loss")), _number(row.get("target_price"))
    if stop is not None and current_close <= stop:
        return {**base, "action": "exit_next_open", "reasons": ["short_term_stop_loss"], "risks": []}
    if target is not None and current_close >= target:
        return {**base, "action": "reduce_next_open", "reasons": ["short_term_target_reached"], "risks": []}
    if purchase_date and sessions_held >= 10:
        return {**base, "action": "exit_next_open", "reasons": ["short_term_time_exit"], "risks": []}
    return {**base, "action": "hold", "reasons": ["short_term_rule_intact"], "risks": []}


def build_short_term_decisions(
    database: Database,
    market_context: dict,
    as_of_date: date | None = None,
    limit: int = 20,
    *,
    historical_replay: bool = False,
    tracked_symbols: set[str] | None = None,
) -> dict:
    """Build the fixed ranking from information available at ``as_of_date``.

    Historical replay deliberately disables the dividend/event blocker because
    the current event table has an ex-date but no announcement timestamp.  Using
    today's complete event table for an old decision date would introduce
    look-ahead bias.  The ranking factors themselves remain unchanged.
    """
    as_of_date = as_of_date or date.today()
    end_of_day_data_cutoff = (
        (as_of_date - timedelta(days=1)).isoformat() if historical_replay else None
    )
    candidates, fundamental_rejections = (
        _evaluated_candidates(
            database, as_of_date, end_of_day_data_cutoff=end_of_day_data_cutoff
        )
        if end_of_day_data_cutoff
        else _evaluated_candidates(database, as_of_date)
    )
    passed_candidate_count_all_dates = len(candidates)
    market_as_of = _iso_date(market_context.get("as_of"))
    eligible_market_coverage = {}
    for market in ("TWSE", "TPEx"):
        market_candidates = [row for row in candidates if row.get("market") == market]
        exact = sum(_iso_date(row.get("latest_price_date")) == market_as_of
                    for row in market_candidates)
        total = len(market_candidates)
        eligible_market_coverage[market] = {
            "recent_symbols": total,
            "exact_date_symbols": exact,
            "exact_date_coverage_percent": round(exact / total * 100, 2) if total else 0.0,
            "universe": "通過基本面安全門檻、可能參與短線排行榜的股票",
        }
    date_counts = Counter(str(row.get("latest_price_date")) for row in candidates
                          if row.get("latest_price_date"))
    common_signal_date = (max(date_counts, key=lambda value: (date_counts[value], value))
                          if date_counts else None)
    candidates = [row for row in candidates
                  if str(row.get("latest_price_date")) == common_signal_date]
    eligible_signal_date_count = len(candidates)
    cutoff = as_of_date.isoformat()
    price_map = {row["symbol"]: database.get_prices(row["symbol"], 120, end_date=cutoff)
                 for row in candidates}
    technical_map = {symbol: calculate_technical_indicators(prices)
                     for symbol, prices in price_map.items()}
    industry_values: dict[str, list[dict]] = {}
    for row in candidates:
        industry = row.get("industry") or "未分類"
        indicators = technical_map[row["symbol"]]["indicators"]
        industry_values.setdefault(industry, []).append({
            "symbol": row["symbol"],
            "return_5d": _number(indicators.get("return_5d_percent")),
            "return_10d": _number(indicators.get("return_10d_percent")),
        })
    industry_contexts = {}
    for row in candidates:
        industry = row.get("industry") or "未分類"
        peers = [item for item in industry_values[industry] if item["symbol"] != row["symbol"]]
        returns5 = [item["return_5d"] for item in peers if item["return_5d"] is not None]
        returns10 = [item["return_10d"] for item in peers if item["return_10d"] is not None]
        enough5, enough10 = len(returns5) >= MIN_INDUSTRY_PEERS, len(returns10) >= MIN_INDUSTRY_PEERS
        industry_contexts[(industry, row["symbol"])] = {
            "status": "available" if enough5 and enough10 else "insufficient_peers",
            "return_5d_percent": round(median(returns5), 4) if enough5 else None,
            "return_10d_percent": round(median(returns10), 4) if enough10 else None,
            "breadth_positive_5d_percent": round(sum(value > 0 for value in returns5) / len(returns5) * 100, 2)
                if enough5 else None,
            "constituent_count": min(len(returns5), len(returns10)),
            "minimum_peer_count": MIN_INDUSTRY_PEERS,
            "subject_excluded": True,
            "method": "通過基本面安全門檻的同產業股票中位數；排除個股自身且至少需要 3 檔同業",
        }
    decisions = []
    for row in candidates:
        symbol = row["symbol"]
        signal_date = _iso_date(row.get("latest_price_date")) or cutoff
        candidate_context = dict(market_context)
        market_aligned = market_as_of == signal_date
        if not market_aligned:
            candidate_context.update({"market_score": None, "index_change_5d": None,
                                      "index_change_20d": None, "events": []})
        candidate_context["data_aligned_to_signal"] = market_aligned
        trades = (
            database.get_institutional_trades(
                symbol, 10, end_date=end_of_day_data_cutoff or signal_date,
                market=str(row.get("market") or "")
            )
            if hasattr(database, "get_institutional_trades") else []
        )
        dividends = (
            [] if historical_replay
            else database.get_dividend_events(symbol, 30)
            if hasattr(database, "get_dividend_events") else []
        )
        decisions.append(_decision_for_candidate(
            row, price_map[symbol], candidate_context, technical_map[symbol],
            industry_contexts.get((row.get("industry") or "未分類", symbol)), trades, dividends,
            date.fromisoformat(signal_date)
        ))
    for decision in decisions:
        score, evidence, risks, components = _research_priority_score(decision)
        attention_grade = _attention_grade(score, decision)
        operation_status, operation_reason = _execution_status(decision)
        decision["attention_score"] = score
        decision["attention_grade"] = attention_grade
        decision["attention_score_components"] = components
        decision["operation_status"] = operation_status
        decision["operation_reason"] = operation_reason
        decision["technical_trigger_status"] = (
            "confirmed" if decision.get("trade_plan", {}).get("analysis_status") == "PASS"
            else "waiting"
        )
        decision["investment_status"] = (
            "conditional_candidate" if operation_status in {"ready", "ready_with_risk"}
            else "do_not_buy" if operation_status in {"blocked", "blocked_overextended", "blocked_fundamental", "reject_rr"}
            else "watch"
        )
        decision["operation_gap"] = _operation_gap(decision)
        # Compatibility fields now explicitly mean attention priority.
        decision["research_priority_score"] = score
        decision["research_score_components"] = components
        decision["candidate_grade"] = attention_grade
        decision["ranking_evidence"] = evidence
        decision["ranking_risks"] = risks
        plan = decision.get("trade_plan", {})
        entry, breakout = _number(plan.get("reference_entry")), _number(plan.get("breakout_level"))
        decision["distance_to_breakout_percent"] = (round((breakout / entry - 1) * 100, 4)
                                                     if entry and breakout is not None else None)
        decision["observation_status"] = {
            "A": "優先關注：方向、相對強度與流動性較完整",
            "B": "次優先關注：具備部分短線優勢",
            "C": "一般觀察：基本面已通過，技術優勢仍有限",
            "D": "暫停關注：事件或資料問題",
        }[attention_grade]
    grade_priority = {"A": 0, "B": 1, "C": 2, "D": 3}
    decisions.sort(key=lambda row: (grade_priority[row["candidate_grade"]],
                                    -row["attention_score"],
                                    -float(row["average_turnover_20"])))
    def with_industry_cap(source: list[dict]) -> list[dict]:
        selected, counts = [], Counter()
        for item in source:
            industry = item.get("industry") or "未分類"
            if counts[industry] >= 3:
                continue
            selected.append(item)
            counts[industry] += 1
            if len(selected) >= limit:
                break
        return selected

    observations = with_industry_cap(decisions)
    # Do not refill from an already-full industry merely to force exactly
    # ``limit`` rows; a shorter diversified list is more truthful.
    operation_ready = [row for row in decisions
                       if row.get("operation_status") in {"ready", "ready_with_risk"}]
    operation_ready.sort(key=lambda row: (
        0 if row["operation_status"] == "ready" else 1,
        -row["attention_score"], -float(row["average_turnover_20"]),
    ))
    operation_ready = with_industry_cap(operation_ready)
    tracked_symbols = {str(symbol) for symbol in (tracked_symbols or set())}
    tracked_candidate_statuses = [
        _compact_tracking_status(row)
        for row in decisions
        if str(row.get("symbol")) in tracked_symbols
    ]
    # "Closest" is a drill-down of the visible attention list, not a second
    # whole-market ranking. RR failures are final rejects for the current plan
    # and are shown on their attention cards instead of being called near-ready.
    closest_operation = [row for row in observations
                         if row.get("operation_status") == "waiting_trigger"]
    closest_operation.sort(key=_closest_operation_sort_key)
    executable: list[dict] = []
    signal_date = common_signal_date
    response_market_mode = market_mode(market_context) if market_as_of == signal_date else "unavailable"
    return {
        "as_of_date": as_of_date.isoformat(), "signal_date": signal_date, "research_only": True,
        "strategy_version": STRATEGY_VERSION, "market_mode": response_market_mode,
        "market_data_as_of": market_as_of,
        "market_data_aligned": market_as_of == signal_date,
        "eligible_market_date_coverage": eligible_market_coverage,
        "candidate_universe_counts": {
            "passed_fundamental_gate_all_recent_dates": passed_candidate_count_all_dates,
            "eligible_on_common_signal_date": eligible_signal_date_count,
            "ranked_before_industry_cap": len(decisions),
            "published_after_industry_cap": len(observations),
        },
        "historical_replay_policy": {
            "enabled": historical_replay,
            "dividend_and_event_blocker_enabled": not historical_replay,
            "reason": (
                "disabled_without_point_in_time_announcement_timestamp"
                if historical_replay else "live_point_in_time_context"
            ),
            "valuation_and_institution_cutoff": end_of_day_data_cutoff,
        },
        "signal_date_selection": {
            "method": "通過安全門檻股票中最常見的最新交易日，避免混用不同交易日排名",
            "date_counts": dict(sorted(date_counts.items(), reverse=True)[:5]),
        },
        "fundamental_gate": {
            "passed": len(candidates),
            "rejected": sum(
                row.get("fundamental_assessment", {}).get("status") != "data_pending"
                for row in fundamental_rejections
            ),
            "data_pending": sum(
                row.get("fundamental_assessment", {}).get("status") == "data_pending"
                for row in fundamental_rejections
            ),
            "rules": [
            "至少 60 個交易日、價格與財報新鮮、至少 4 期財報",
            "20 日平均成交金額至少 500 萬元", "負債比不高於 70%",
            "最新淨利與營業利益須為正，近四季自由現金流不得為負；缺值不視為零",
            f"以訊號日收盤與近四季 EPS 重算本益比，不得高於 {MAX_PE_RATIO:g} 倍",
            f"最新月營收年增率不得低於 {MIN_REVENUE_YOY_PERCENT:g}%",
            f"本益比高於 {HIGH_PE_REVIEW_THRESHOLD:g} 倍時，月營收年增至少 {MIN_HIGH_PE_REVENUE_YOY_PERCENT:g}%、本業獲利不得衰退，且本業獲利占比至少 {MIN_CORE_EARNINGS_RATIO_PERCENT:g}%",
            "若近四季 EPS 與官方本益比反推獲利差異超過 100%，暫停判定並先同步財報",
        ], "pe_ceiling": MAX_PE_RATIO, "revenue_yoy_floor": MIN_REVENUE_YOY_PERCENT,
            "high_pe_review_threshold": HIGH_PE_REVIEW_THRESHOLD},
        "market_score_policy": {
            "defensive": "市場分數低於 40 不再單獨封鎖進場；歷史上仍可能上漲，但最差路徑較深。若未來進場規則獲驗證，只允許最多 2.5% 新增部位。",
            "trend": "市場分數至少 55 且 20 日大盤報酬非負，按一般風險上限評估。",
            "range": "介於上述兩者，按一般風險上限評估。",
        },
        "technical_rules": {
            "trend_breakout": "收盤突破 20 日高點；量比依市場為 1.2／1.3／1.5 倍；停損風險不得超過 1.5 ATR",
            "ranking": "值得關注只評估趨勢、相對強度、流動性、法人確認與風險；突破和暫定 RR 不影響名次",
            "execution": "次日進場不得高於收盤加 0.25 ATR；目標獨立取自結構壓力或固定 2 ATR 延伸，再以成本後 RR 檢查",
            "chase_control": "5 日漲幅至少 20%，且 MA5／MA20 乖離、布林上軌、RSI 中至少兩項過熱時，保留關注但禁止隔日追價",
        },
        "attention_grade_policy": {
            "A": "關注分數至少 65；優先關注",
            "B": "關注分數 45 至 64；次優先關注",
            "C": "關注分數低於 45；一般觀察",
            "D": "重大事件或資料日期問題；暫停關注",
            "important": "關注等級不代表今日可買；操作狀態另行判斷。",
        },
        "industry_concentration_policy": {
            "maximum_stocks_per_industry_in_top_list": 3,
            "hard_limit": True,
            "actual_counts": dict(Counter((row.get("industry") or "未分類") for row in observations)),
        },
        "decisions": observations,
        "observation_rankings": observations,
        "attention_rankings": observations,
        "operation_ready_candidates": operation_ready[:limit],
        "tracked_candidate_statuses": tracked_candidate_statuses,
        "closest_operation_candidates": with_industry_cap(closest_operation)[:min(limit, 5)],
        "analysis_pass_candidates": operation_ready[:limit],
        "fundamental_rejections": [
            {
                "symbol": row.get("symbol"), "market": row.get("market"),
                "name": row.get("name"), "industry": row.get("industry"),
                "close": row.get("close"), "latest_price_date": row.get("latest_price_date"),
                "fundamental_snapshot": row.get("fundamental_assessment"),
            }
            for row in [item for item in fundamental_rejections
                        if item.get("fundamental_assessment", {}).get("status") != "data_pending"][:limit]
        ],
        "fundamental_data_pending": [
            {
                "symbol": row.get("symbol"), "market": row.get("market"),
                "name": row.get("name"), "industry": row.get("industry"),
                "close": row.get("close"), "latest_price_date": row.get("latest_price_date"),
                "fundamental_snapshot": row.get("fundamental_assessment"),
            }
            for row in [item for item in fundamental_rejections
                        if item.get("fundamental_assessment", {}).get("status") == "data_pending"][:limit]
        ],
        "execution_candidates": executable[:limit],
        "execution_governance": {"new_entries_enabled": False,
                                   "reason": "分析通過與交易權限分離：v2 尚未完成鎖定規則的樣本外與紙上驗證，目前只提供條件式紙上操作。"},
        "limitations": [
            "僅限 TWSE／TPEx 日資料；沒有 15／60 分 K。",
            "處置、注意與暫停交易名單尚未接入，因此任何候選在開盤前仍須查核。",
            "未驗證為正式策略，不保證獲利或提供自動下單。",
        ],
    }
