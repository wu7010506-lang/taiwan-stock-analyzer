from __future__ import annotations

"""Point-in-time fundamental safety gate shared by short-term views.

The interface intentionally returns both the verdict and every input needed to
verify it.  Technical confirmation is evaluated elsewhere and can never turn a
failed fundamental verdict into an operation-ready candidate.
"""

import re
from datetime import date

from app.database import Database
from app.point_in_time import financial_available_sql, revenue_available_sql

MAX_PE_RATIO = 60.0
HIGH_PE_REVIEW_THRESHOLD = 40.0
MAX_DEBT_RATIO_PERCENT = 70.0
MIN_REVENUE_YOY_PERCENT = 0.0
MIN_HIGH_PE_REVENUE_YOY_PERCENT = 20.0
MIN_CORE_EARNINGS_RATIO_PERCENT = 60.0
MIN_HIGH_PE_OPERATING_INCOME_YOY_PERCENT = 0.0
MAX_PE_CROSS_CHECK_DIFFERENCE_PERCENT = 100.0


def _official_financial_period(value: object) -> tuple[int, int] | None:
    """Normalize valuation-feed periods such as ``115/2`` or ``115年第2季``."""
    numbers = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    if len(numbers) < 2 or numbers[1] not in range(1, 5):
        return None
    year = numbers[0] + 1911 if numbers[0] < 1911 else numbers[0]
    return (year, numbers[1]) if 1900 <= year <= 2200 else None


def _valuation_date_iso(value: object) -> str | None:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _quarter_index(row: dict) -> int:
    return int(row.get("fiscal_year") or 0) * 4 + int(row.get("fiscal_quarter") or 0)


def _four_consecutive(rows: list[dict]) -> list[dict]:
    ordered = sorted(rows, key=_quarter_index, reverse=True)
    if len(ordered) < 4:
        return []
    latest = ordered[:4]
    indexes = [_quarter_index(row) for row in latest]
    return latest if indexes == list(range(indexes[0], indexes[0] - 4, -1)) else []


def _rollforward(
    latest: dict,
    rows: list[dict],
    field: str,
) -> float | None:
    """Convert a cumulative YTD value to TTM using prior annual and prior YTD."""
    current = _number(latest.get(field))
    quarter = int(latest.get("fiscal_quarter") or 0)
    year = int(latest.get("fiscal_year") or 0)
    if current is None:
        return None
    if quarter == 4:
        return current
    prior_annual = next(
        (_number(row.get(field)) for row in rows
         if int(row.get("fiscal_year") or 0) == year - 1
         and int(row.get("fiscal_quarter") or 0) == 4),
        None,
    )
    prior_same = next(
        (_number(row.get(field)) for row in rows
         if int(row.get("fiscal_year") or 0) == year - 1
         and int(row.get("fiscal_quarter") or 0) == quarter),
        None,
    )
    if prior_annual is None or prior_same is None:
        return None
    return prior_annual - prior_same + current


def _ttm_income_value(latest: dict, rows: list[dict], field: str) -> float | None:
    """FinMind income rows are single-quarter; official OpenAPI rows are YTD."""
    source = str(latest.get("source") or "")
    report_type = str(latest.get("report_type") or "")
    if report_type == "finmind" or "FinMind" in source:
        quarters = _four_consecutive(rows)
        values = [_number(row.get(field)) for row in quarters]
        return sum(values) if len(values) == 4 and all(value is not None for value in values) else None
    current = _number(latest.get(field))
    quarter = int(latest.get("fiscal_quarter") or 0)
    year = int(latest.get("fiscal_year") or 0)
    # The latest official row is cumulative YTD, while historical FinMind rows
    # are single-quarter.  Complete the TTM value with only the prior-year
    # quarters after the current fiscal quarter.
    prior_tail = [
        row for row in rows
        if int(row.get("fiscal_year") or 0) == year - 1
        and int(row.get("fiscal_quarter") or 0) > quarter
        and (str(row.get("report_type") or "") == "finmind" or "FinMind" in str(row.get("source") or ""))
    ]
    tail_values = [_number(row.get(field)) for row in prior_tail]
    if current is not None and len(prior_tail) == 4 - quarter and all(value is not None for value in tail_values):
        return current + sum(tail_values)
    return _rollforward(latest, rows, field)


def _plausible_cash_flow(row: dict) -> float | None:
    value = _number(row.get("free_cash_flow"))
    revenue = _number(row.get("revenue"))
    if value is None:
        return None
    # Some previously normalized official rows contain a 1,000x cash-flow
    # scale error.  A ten-times-revenue bound is deliberately generous and
    # only rejects clearly impossible units, not ordinary business volatility.
    if revenue and abs(value) > abs(revenue) * 10:
        return None
    return value


def summarize_financial_rows(rows: list[dict]) -> dict:
    if not rows:
        return {}
    ordered = sorted(rows, key=_quarter_index, reverse=True)
    latest = ordered[0]
    year = int(latest.get("fiscal_year") or 0)
    quarter = int(latest.get("fiscal_quarter") or 0)
    prior_same = next(
        (row for row in ordered
         if int(row.get("fiscal_year") or 0) == year - 1
         and int(row.get("fiscal_quarter") or 0) == quarter),
        {},
    )
    latest_operating = _number(latest.get("operating_income"))
    prior_operating = _number(prior_same.get("operating_income"))
    latest_is_official_ytd = not (
        str(latest.get("report_type") or "") == "finmind"
        or "FinMind" in str(latest.get("source") or "")
    )
    if latest_is_official_ytd and quarter > 1:
        prior_ytd_rows = [
            row for row in ordered
            if int(row.get("fiscal_year") or 0) == year - 1
            and 1 <= int(row.get("fiscal_quarter") or 0) <= quarter
            and (str(row.get("report_type") or "") == "finmind" or "FinMind" in str(row.get("source") or ""))
        ]
        values = [_number(row.get("operating_income")) for row in prior_ytd_rows]
        if len(values) == quarter and all(value is not None for value in values):
            prior_operating = sum(values)
    operating_yoy = (
        (latest_operating / abs(prior_operating) - 1) * 100
        if latest_operating is not None and prior_operating not in (None, 0) else None
    )
    prior_annual = next(
        (row for row in ordered
         if int(row.get("fiscal_year") or 0) == year - 1
         and int(row.get("fiscal_quarter") or 0) == 4),
        {},
    )
    current_fcf = _plausible_cash_flow(latest)
    prior_annual_fcf = _plausible_cash_flow(prior_annual)
    prior_same_fcf = _plausible_cash_flow(prior_same)
    if quarter == 4 and current_fcf is not None:
        ttm_fcf = current_fcf
        cash_flow_safety_value = current_fcf
        cash_flow_method = "latest_completed_fiscal_year"
    elif current_fcf is not None and prior_annual_fcf is not None and prior_same_fcf is not None:
        ttm_fcf = prior_annual_fcf - prior_same_fcf + current_fcf
        cash_flow_safety_value = ttm_fcf
        cash_flow_method = "ttm_rollforward_from_cumulative_cash_flow"
    else:
        ttm_fcf = None
        cash_flow_safety_value = prior_annual_fcf
        cash_flow_method = (
            "latest_completed_fiscal_year_fallback_due_missing_or_invalid_current_cash_flow"
            if prior_annual_fcf is not None else "unavailable"
        )
    return {
        "latest_financial_date": latest.get("statement_date"),
        "latest_financial_published_date": latest.get("published_date"),
        "latest_financial_fetched_at": latest.get("fetched_at"),
        "latest_fiscal_year": year,
        "latest_fiscal_quarter": quarter,
        "latest_report_type": latest.get("report_type"),
        "latest_financial_source": latest.get("source"),
        "financial_periods": len(ordered),
        "total_assets": _number(latest.get("total_assets")),
        "total_liabilities": _number(latest.get("total_liabilities")),
        "latest_operating_income": latest_operating,
        "previous_same_period_operating_income": prior_operating,
        "operating_income_yoy_percent": operating_yoy,
        "latest_net_income": _number(latest.get("net_income")),
        "latest_free_cash_flow": _number(latest.get("free_cash_flow")),
        "ttm_eps": _ttm_income_value(latest, ordered, "eps"),
        "ttm_net_income": _ttm_income_value(latest, ordered, "net_income"),
        "ttm_operating_income": _ttm_income_value(latest, ordered, "operating_income"),
        # Cash-flow statements are cumulative YTD in the stored FinMind/MOPS
        # feed, so summing four rows would double count earlier quarters.
        "ttm_free_cash_flow": ttm_fcf,
        "cash_flow_safety_value": cash_flow_safety_value,
        "cash_flow_method": cash_flow_method,
    }


def assess_short_term_fundamentals(inputs: dict) -> dict:
    close = _number(inputs.get("close"))
    ttm_eps = _number(inputs.get("ttm_eps"))
    ttm_net_income = _number(inputs.get("ttm_net_income"))
    reported_pe = _number(inputs.get("reported_pe_ratio"))
    valuation_close = _number(inputs.get("valuation_close"))
    reported_implied_ttm_eps = (
        valuation_close / reported_pe
        if valuation_close is not None and reported_pe and reported_pe > 0
        else None
    )
    rounded_eps_cancellation = (
        ttm_eps is not None
        and abs(ttm_eps) < 1e-9
        and ttm_net_income is not None
        and ttm_net_income > 0
        and reported_implied_ttm_eps is not None
        and reported_implied_ttm_eps > 0
    )
    reliable_ttm_eps = None if rounded_eps_cancellation else ttm_eps
    ttm_pe = (
        close / reliable_ttm_eps
        if close is not None and reliable_ttm_eps and reliable_ttm_eps > 0
        else None
    )
    adjusted_reported_pe = (
        reported_pe * close / valuation_close
        if reported_pe is not None and close is not None and valuation_close else None
    )
    pe_cross_check_difference = (
        abs(ttm_pe - adjusted_reported_pe) / adjusted_reported_pe * 100
        if ttm_pe is not None and adjusted_reported_pe else None
    )
    if ttm_pe is not None and (pe_cross_check_difference is None or pe_cross_check_difference <= 5):
        effective_pe = ttm_pe
        pe_method = "訊號日收盤價 ÷ 最近四季 EPS；並與官方本益比交叉驗證"
    elif adjusted_reported_pe is not None:
        effective_pe = adjusted_reported_pe
        pe_method = "官方本益比依估值日與訊號日收盤價比例調整；近四季 EPS 重建值未通過交叉驗證"
    else:
        effective_pe = ttm_pe
        pe_method = "訊號日收盤價 ÷ 最近四季 EPS；缺少官方本益比交叉驗證"
    if rounded_eps_cancellation:
        pe_method = "official_pe_due_to_rounded_quarterly_eps_cancellation"
    reported_pb = _number(inputs.get("reported_pb_ratio"))
    effective_pb = (
        reported_pb * close / valuation_close
        if reported_pb is not None and close is not None and valuation_close else reported_pb
    )
    total_assets = _number(inputs.get("total_assets"))
    total_liabilities = _number(inputs.get("total_liabilities"))
    debt_ratio = (
        total_liabilities / total_assets * 100
        if total_liabilities is not None and total_assets else None
    )
    latest_operating = _number(inputs.get("latest_operating_income"))
    latest_net = _number(inputs.get("latest_net_income"))
    core_ratio = (
        latest_operating / latest_net * 100
        if latest_operating is not None and latest_net and latest_net > 0 else None
    )
    operating_yoy = _number(inputs.get("operating_income_yoy_percent"))
    revenue_yoy = _number(inputs.get("latest_revenue_yoy_percent"))
    ttm_fcf = _number(inputs.get("ttm_free_cash_flow"))
    cash_flow_safety_value = _number(inputs.get("cash_flow_safety_value"))

    blockers: list[str] = []
    codes: list[str] = []
    missing: list[str] = []

    def block(code: str, reason: str) -> None:
        codes.append(code)
        blockers.append(reason)

    if inputs.get("valuation_financial_period_missing"):
        block(
            "official_valuation_financial_period_missing",
            "Official valuation references a newer financial period that is not "
            "available locally; refresh the matching statement before evaluation.",
        )

    if (
        pe_cross_check_difference is not None
        and pe_cross_check_difference > MAX_PE_CROSS_CHECK_DIFFERENCE_PERCENT
    ):
        block(
            "valuation_earnings_mismatch_requires_refresh",
            "近四季 EPS 與證交所本益比反推獲利差異"
            f" {pe_cross_check_difference:.1f}%，超過"
            f" {MAX_PE_CROSS_CHECK_DIFFERENCE_PERCENT:g}% 的資料同步上限；"
            "暫停判定並先更新最新財報。",
        )

    if debt_ratio is None:
        missing.append("負債比資料不足")
    elif debt_ratio > MAX_DEBT_RATIO_PERCENT:
        block("debt_ratio_above_limit", f"負債比 {debt_ratio:.1f}% 高於 {MAX_DEBT_RATIO_PERCENT:g}%")
    if latest_net is None:
        missing.append("最新淨利資料不足")
    elif latest_net < 0:
        block("latest_net_income_negative", "最新一期仍為虧損")
    if latest_operating is None:
        missing.append("最新營業利益資料不足")
    elif latest_operating <= 0:
        block("latest_operating_income_non_positive", "最新一期本業營業利益未轉正")
    if cash_flow_safety_value is None:
        missing.append("自由現金流安全值資料不足")
    elif cash_flow_safety_value < 0:
        block("free_cash_flow_safety_value_negative", f"自由現金流安全值為負（{cash_flow_safety_value:,.0f} 元）")
    if effective_pe is None:
        missing.append("同訊號日近四季本益比無法計算")
    elif effective_pe > MAX_PE_RATIO:
        block("pe_above_absolute_limit", f"同訊號日本益比 {effective_pe:.1f} 倍高於 {MAX_PE_RATIO:g} 倍上限")
    if revenue_yoy is None:
        missing.append("最新月營收年增率資料不足")
    elif revenue_yoy < MIN_REVENUE_YOY_PERCENT:
        block("revenue_yoy_negative", f"最新月營收年減 {abs(revenue_yoy):.1f}%")

    if effective_pe is not None and HIGH_PE_REVIEW_THRESHOLD < effective_pe <= MAX_PE_RATIO:
        if revenue_yoy is None or revenue_yoy < MIN_HIGH_PE_REVENUE_YOY_PERCENT:
            block(
                "high_pe_without_revenue_growth",
                f"本益比 {effective_pe:.1f} 倍偏高，但月營收年增未達 {MIN_HIGH_PE_REVENUE_YOY_PERCENT:g}%",
            )
        if operating_yoy is None:
            missing.append("高本益比股票缺少本業獲利年增驗證")
        elif operating_yoy < MIN_HIGH_PE_OPERATING_INCOME_YOY_PERCENT:
            block(
                "high_pe_operating_income_decline",
                f"本益比 {effective_pe:.1f} 倍偏高，且本業營業利益年減 {abs(operating_yoy):.1f}%",
            )
        if core_ratio is None:
            missing.append("高本益比股票缺少本業獲利占比驗證")
        elif core_ratio < MIN_CORE_EARNINGS_RATIO_PERCENT:
            block(
                "high_pe_low_core_earnings_share",
                f"本業營業利益只相當於最新稅後淨利的 {core_ratio:.1f}%，低於 {MIN_CORE_EARNINGS_RATIO_PERCENT:g}%",
            )

    for reason in missing:
        block("missing_required_fundamental_data", reason)

    data_pending = bool({
        "valuation_earnings_mismatch_requires_refresh",
        "official_valuation_financial_period_missing",
    }.intersection(codes))
    return {
        "passed": not blockers,
        "status": "pass" if not blockers else "data_pending" if data_pending else "blocked",
        "blocking_codes": codes,
        "blocking_reasons": blockers,
        "price_date": inputs.get("latest_price_date"),
        "financial_date": inputs.get("latest_financial_date"),
        "financial_available_date": inputs.get("latest_financial_available_date"),
        "financial_availability_method": inputs.get("financial_availability_method"),
        "valuation_source_date": inputs.get("latest_valuation_date"),
        "valuation_financial_period": inputs.get("valuation_financial_period"),
        "valuation_financial_period_missing": bool(inputs.get("valuation_financial_period_missing")),
        "revenue_month": inputs.get("latest_revenue_month"),
        "close": close,
        "ttm_eps": (
            None if rounded_eps_cancellation
            else round(ttm_eps, 4) if ttm_eps is not None else None
        ),
        "reported_implied_ttm_eps": (
            round(reported_implied_ttm_eps, 4)
            if reported_implied_ttm_eps is not None else None
        ),
        "ttm_eps_reconstruction_status": (
            "unreliable_rounded_quarterly_eps_cancellation"
            if rounded_eps_cancellation else "available" if ttm_eps is not None else "unavailable"
        ),
        "pe_ratio": round(effective_pe, 4) if effective_pe is not None else None,
        "pe_method": pe_method,
        "pe_from_ttm_eps": round(ttm_pe, 4) if ttm_pe is not None else None,
        "pe_cross_check_difference_percent": round(pe_cross_check_difference, 4) if pe_cross_check_difference is not None else None,
        "pe_cross_check_block_threshold_percent": MAX_PE_CROSS_CHECK_DIFFERENCE_PERCENT,
        "requires_financial_refresh": data_pending,
        "reported_pe_ratio": reported_pe,
        "reported_pe_adjusted_to_signal_price": round(adjusted_reported_pe, 4) if adjusted_reported_pe is not None else None,
        "pe_ceiling": MAX_PE_RATIO,
        "high_pe_review_threshold": HIGH_PE_REVIEW_THRESHOLD,
        "pb_ratio": round(effective_pb, 4) if effective_pb is not None else None,
        "reported_pb_ratio": reported_pb,
        "dividend_yield_percent": _number(inputs.get("dividend_yield_percent")),
        "debt_ratio_percent": round(debt_ratio, 4) if debt_ratio is not None else None,
        "debt_ratio_ceiling_percent": MAX_DEBT_RATIO_PERCENT,
        "latest_operating_income": latest_operating,
        "latest_net_income": latest_net,
        "core_earnings_ratio_percent": round(core_ratio, 4) if core_ratio is not None else None,
        "core_earnings_ratio_floor_percent": MIN_CORE_EARNINGS_RATIO_PERCENT,
        "operating_income_yoy_percent": round(operating_yoy, 4) if operating_yoy is not None else None,
        "ttm_free_cash_flow": ttm_fcf,
        "free_cash_flow_safety_value": cash_flow_safety_value,
        "free_cash_flow_method": inputs.get("cash_flow_method"),
        "revenue_yoy_percent": revenue_yoy,
        "high_pe_revenue_yoy_floor_percent": MIN_HIGH_PE_REVENUE_YOY_PERCENT,
        "limitations": [
            "本業獲利占比以營業利益／稅後淨利作保守代理；資料庫尚未完整保存稅前與業外損益。",
            "本門檻只排除明顯風險，不等於公司品質或合理價值的完整估值。",
        ],
    }


def load_short_term_fundamental_assessment(
    database: Database,
    symbol: str,
    market: str,
    signal_date: str,
    close: float,
    *,
    end_of_day_data_cutoff: str | None = None,
) -> dict:
    valuation_cutoff = end_of_day_data_cutoff or signal_date
    financial_available = financial_available_sql("statement_date")
    revenue_available = revenue_available_sql("revenue_month")
    with database.connect() as connection:
        valuation = connection.execute(
            """SELECT v.*, p.close AS valuation_close
               FROM valuations v
               LEFT JOIN daily_prices p ON p.symbol=v.symbol AND p.market=v.market
                 AND date(p.trade_date)=date(CASE WHEN length(v.valuation_date)=8
                    THEN substr(v.valuation_date,1,4)||'-'||substr(v.valuation_date,5,2)||'-'||substr(v.valuation_date,7,2)
                    ELSE v.valuation_date END)
               WHERE v.symbol=? AND v.market=?
                 AND date(CASE WHEN length(v.valuation_date)=8
                    THEN substr(v.valuation_date,1,4)||'-'||substr(v.valuation_date,5,2)||'-'||substr(v.valuation_date,7,2)
                    ELSE v.valuation_date END)<=date(?)
               ORDER BY date(CASE WHEN length(v.valuation_date)=8
                    THEN substr(v.valuation_date,1,4)||'-'||substr(v.valuation_date,5,2)||'-'||substr(v.valuation_date,7,2)
                    ELSE v.valuation_date END) DESC LIMIT 1""",
            (symbol, market, valuation_cutoff),
        ).fetchone()
        valuation_row = dict(valuation) if valuation else {}
        valuation_period = _official_financial_period(
            valuation_row.get("financial_period")
        )
        financial_period_clause = ""
        financial_parameters: list[object] = [symbol, market, signal_date]
        if valuation_period:
            # A dated official valuation row that explicitly cites a fiscal
            # period is contemporaneous evidence that the exchange had already
            # incorporated that filing.  This is stronger point-in-time
            # evidence than the generic 45/90-day fallback lag.
            financial_period_clause = " OR (fiscal_year=? AND fiscal_quarter=?)"
            financial_parameters.extend(valuation_period)
        financial_rows = [dict(row) for row in connection.execute(
            f"""SELECT * FROM financial_snapshots
                WHERE symbol=? AND market=? AND statement_date IS NOT NULL
                  AND ({financial_available}<=date(?) {financial_period_clause})
                ORDER BY fiscal_year DESC, fiscal_quarter DESC LIMIT 8""",
            financial_parameters,
        ).fetchall()]
        revenue = connection.execute(
            f"""SELECT * FROM monthly_revenues
                WHERE symbol=? AND market=? AND {revenue_available}<=date(?)
                ORDER BY revenue_month DESC LIMIT 1""",
            (symbol, market, signal_date),
        ).fetchone()

    summary = summarize_financial_rows(financial_rows)
    revenue_row = dict(revenue) if revenue else {}
    fiscal_quarter = int(summary.get("latest_fiscal_quarter") or 0)
    financial_date = summary.get("latest_financial_date")
    available_date = summary.get("latest_financial_published_date")
    latest_period = (
        int(summary.get("latest_fiscal_year") or 0),
        int(summary.get("latest_fiscal_quarter") or 0),
    )
    valuation_financial_period_missing = bool(
        valuation_period and latest_period < valuation_period
    )
    if valuation_period and latest_period == valuation_period:
        available_date = _valuation_date_iso(valuation_row.get("valuation_date"))
        availability_method = "official_valuation_financial_period"
    elif available_date:
        availability_method = "verified_filing_date"
    elif financial_date:
        lag_days = 90 if fiscal_quarter == 4 else 45
        lag_ordinal = date.fromisoformat(str(financial_date)).toordinal() + lag_days
        lag_date = date.fromordinal(lag_ordinal).isoformat()
        source = str(summary.get("latest_financial_source") or "")
        fetched_date = _valuation_date_iso(
            str(summary.get("latest_financial_fetched_at") or "")[:10]
        )
        if "official OpenAPI" in source and fetched_date and fetched_date < lag_date:
            available_date = fetched_date
            availability_method = "official_row_first_observed"
        else:
            available_date = lag_date
            availability_method = "conservative_filing_lag"
    else:
        availability_method = "unavailable"
    inputs = {
        **summary,
        "close": close,
        "latest_price_date": signal_date,
        "latest_financial_available_date": available_date,
        "financial_availability_method": availability_method,
        "latest_valuation_date": valuation_row.get("valuation_date"),
        "valuation_financial_period": valuation_row.get("financial_period"),
        "valuation_financial_period_missing": (
            valuation_financial_period_missing
        ),
        "reported_pe_ratio": valuation_row.get("pe_ratio"),
        "reported_pb_ratio": valuation_row.get("pb_ratio"),
        "dividend_yield_percent": valuation_row.get("dividend_yield"),
        "valuation_close": valuation_row.get("valuation_close"),
        "latest_revenue_month": revenue_row.get("revenue_month"),
        "latest_revenue_yoy_percent": revenue_row.get("yoy_percent"),
    }
    return assess_short_term_fundamentals(inputs)
