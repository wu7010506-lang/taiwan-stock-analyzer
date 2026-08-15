from __future__ import annotations

"""Point-in-time replay for the fixed short-term attention ranking.

This module evaluates both ranking predictiveness and a conservative execution
proxy.  A signal is formed after the signal-day close; predictive returns stay
close-to-close for comparability, while the execution proxy enters at the next
session open and exits at the selected horizon close after explicit costs.
"""

from bisect import bisect_right
from collections import defaultdict
from datetime import date
from statistics import mean, median
from typing import Iterable

from app.database import Database
from app.point_in_time import financial_available_sql
from app.short_term_decision import STRATEGY_VERSION, build_short_term_decisions
from app.strategy_governance import lookahead_audit


DEFAULT_HORIZONS = (3, 5, 10)
BACKTEST_VERSION = "short-term-ranking-pit-replay-v2-next-open-costs"
MIN_INDUSTRY_PEERS = 3


def _iso_date(value: object) -> str | None:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if len(text) == 7 and text.isdigit():
        text = f"{int(text[:3]) + 1911:04d}-{text[3:5]}-{text[5:]}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _select_signal_dates(
    database: Database,
    start_date: str,
    end_date: str,
    frequency: str,
    max_signal_dates: int,
) -> tuple[list[str], dict]:
    with database.connect() as connection:
        dates = [row[0] for row in connection.execute(
            """SELECT trade_date FROM market_index_snapshots
               WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date""",
            (start_date, end_date),
        )]
    if frequency == "weekly":
        grouped: dict[tuple[int, int], str] = {}
        for value in dates:
            parsed = date.fromisoformat(value)
            year, week, _ = parsed.isocalendar()
            grouped[(year, week)] = value
        dates = list(grouped.values())
    elif frequency == "monthly":
        grouped = {}
        for value in dates:
            grouped[value[:7]] = value
        dates = list(grouped.values())
    elif frequency != "daily":
        raise ValueError("frequency must be daily, weekly, or monthly")

    original_count = len(dates)
    truncated = original_count > max_signal_dates
    if truncated:
        # Preserve the whole requested period instead of silently returning
        # only the most recent regime.
        indices = {
            round(index * (original_count - 1) / (max_signal_dates - 1))
            for index in range(max_signal_dates)
        } if max_signal_dates > 1 else {original_count - 1}
        dates = [dates[index] for index in sorted(indices)]
    return dates, {
        "frequency": frequency,
        "available_signal_dates": original_count,
        "evaluated_signal_dates": len(dates),
        "max_signal_dates": max_signal_dates,
        "truncated_with_even_period_sampling": truncated,
    }


def _market_context_as_of(database: Database, signal_date: str) -> dict | None:
    with database.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT trade_date,close,market_score,overheat_score,regime
               FROM market_index_snapshots WHERE trade_date<=?
               ORDER BY trade_date DESC LIMIT 121""",
            (signal_date,),
        )]
    if not rows or rows[0]["trade_date"] != signal_date:
        return None
    rows.reverse()
    closes = [float(row["close"]) for row in rows]

    def change(sessions: int) -> float | None:
        return (
            (closes[-1] / closes[-sessions - 1] - 1) * 100
            if len(closes) > sessions else None
        )

    latest = rows[-1]
    score = latest.get("market_score")
    return {
        "available": True,
        "as_of": signal_date,
        "index_close": closes[-1],
        "market_score": float(score) if score is not None else 50.0,
        "market_score_reconstructed_as_neutral": score is None,
        "overheat_score": latest.get("overheat_score"),
        "regime": latest.get("regime") or "unknown",
        "index_change_5d": change(5),
        "index_change_20d": change(20),
        "events": [],
        "data_aligned_to_signal": True,
        "historical_reconstruction": True,
    }


def _factor_coverage_as_of(database: Database, signal_date: str) -> dict:
    """Count current-universe symbols capable of a faithful factor replay.

    The count is a readiness gate, not the candidate selection itself.  It
    mirrors the ranking's minimum histories and additionally requires five
    institutional observations so missing flow cannot silently alter ranks.
    """
    financial_available = financial_available_sql("fs.statement_date")
    sql = f"""
    WITH price AS (
        SELECT i.symbol,i.market,MAX(p.trade_date) AS latest_price,
               COUNT(p.trade_date) AS price_periods
        FROM instruments i
        LEFT JOIN daily_prices p ON p.symbol=i.symbol AND p.market=i.market
          AND p.trade_date<=:as_of
        GROUP BY i.symbol,i.market
    ), financial AS (
        SELECT i.symbol,i.market,COUNT(fs.statement_date) AS financial_periods,
               SUM(CASE WHEN fs.free_cash_flow IS NOT NULL THEN 1 ELSE 0 END) AS fcf_periods,
               MAX({financial_available}) AS latest_financial_available
        FROM instruments i
        LEFT JOIN financial_snapshots fs
          ON fs.symbol=i.symbol AND fs.market=i.market
         AND fs.statement_date IS NOT NULL
         AND {financial_available}<=date(:as_of)
        GROUP BY i.symbol,i.market
    ), valuation AS (
        SELECT i.symbol,i.market,COUNT(v.valuation_date) AS valuation_periods
        FROM instruments i
        LEFT JOIN valuations v ON v.symbol=i.symbol AND v.market=i.market
         AND date(CASE WHEN length(v.valuation_date)=8
                  THEN substr(v.valuation_date,1,4)||'-'||substr(v.valuation_date,5,2)||'-'||substr(v.valuation_date,7,2)
                  ELSE v.valuation_date END)<date(:as_of)
        GROUP BY i.symbol,i.market
    ), revenue AS (
        SELECT i.symbol,i.market,COUNT(r.revenue_month) AS revenue_periods
        FROM instruments i
        LEFT JOIN monthly_revenues r ON r.symbol=i.symbol AND r.market=i.market
         AND date(r.revenue_month||'-01','+1 month','+10 days')<=date(:as_of)
        GROUP BY i.symbol,i.market
    ), institution AS (
        SELECT i.symbol,i.market,COUNT(t.trade_date) AS institution_periods
        FROM instruments i
        LEFT JOIN institutional_trades t
          ON t.symbol=i.symbol AND t.market=i.market
         AND t.trade_date<:as_of AND t.trade_date>date(:as_of,'-14 days')
        GROUP BY i.symbol,i.market
    ), readiness AS (
        SELECT p.symbol,p.market,
               (p.price_periods>=60
                AND date(p.latest_price)>=date(:as_of,'-7 days')) AS price_ready,
               (f.financial_periods>=4 AND f.fcf_periods>=1
                AND date(f.latest_financial_available)>=date(p.latest_price,'-190 days')) AS financial_ready,
               (v.valuation_periods>=1) AS valuation_ready,
               (r.revenue_periods>=1) AS revenue_ready,
               (ins.institution_periods>=5) AS institution_ready
        FROM price p
        JOIN financial f USING(symbol,market)
        JOIN valuation v USING(symbol,market)
        JOIN revenue r USING(symbol,market)
        JOIN institution ins USING(symbol,market)
    )
    SELECT market,COUNT(*) AS current_universe_symbols,
           COALESCE(SUM(price_ready),0) AS price_ready_symbols,
           COALESCE(SUM(financial_ready),0) AS financial_ready_symbols,
           COALESCE(SUM(valuation_ready),0) AS valuation_ready_symbols,
           COALESCE(SUM(revenue_ready),0) AS revenue_ready_symbols,
           COALESCE(SUM(institution_ready),0) AS institution_ready_symbols,
           COALESCE(SUM(price_ready AND financial_ready AND valuation_ready
                        AND revenue_ready),0) AS core_ready_symbols,
           COALESCE(SUM(price_ready AND financial_ready AND valuation_ready
                        AND revenue_ready AND institution_ready),0) AS full_factor_ready_symbols
    FROM readiness GROUP BY market ORDER BY market
    """
    with database.connect() as connection:
        markets = [dict(row) for row in connection.execute(sql, {"as_of": signal_date})]
    fields = (
        "current_universe_symbols", "price_ready_symbols", "financial_ready_symbols",
        "valuation_ready_symbols", "revenue_ready_symbols",
        "institution_ready_symbols", "core_ready_symbols", "full_factor_ready_symbols",
    )
    total = {field: sum(int(row[field] or 0) for row in markets) for field in fields}
    return {"as_of": signal_date, "markets": markets, "total": total}


def _data_cutoff(database: Database) -> dict:
    tables = {
        "price": ("daily_prices", "trade_date"),
        "market": ("market_index_snapshots", "trade_date"),
        "financial": ("financial_snapshots", "statement_date"),
        "valuation": ("valuations", "valuation_date"),
        "revenue": ("monthly_revenues", "revenue_month"),
        "institution": ("institutional_trades", "trade_date"),
    }
    result = {}
    with database.connect() as connection:
        for key, (table, column) in tables.items():
            row = connection.execute(
                f"SELECT MIN({column}),MAX({column}),COUNT(*) FROM {table}"
            ).fetchone()
            result[key] = {"start": row[0], "end": row[1], "rows": row[2]}
    return result


def _audit_available_at(item: dict, signal_date: str) -> str:
    values = [signal_date]
    for value in (
        item.get("latest_financial_available_date"),
        item.get("latest_revenue_available_date"),
        (item.get("institutional_flow") or {}).get("as_of"),
        item.get("latest_valuation_date"),
    ):
        normalized = _iso_date(value)
        if normalized:
            values.append(normalized)
    return max(values)


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(mean(clean), 4) if clean else None


def _median(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(median(clean), 4) if clean else None


def _summarize(items: list[dict], horizons: tuple[int, ...]) -> dict:
    summary = {}
    for horizon in horizons:
        rows = [item["horizons"][str(horizon)] for item in items]
        matured = [row for row in rows if row.get("matured")]
        executions = [
            row["execution"] for row in matured
            if (row.get("execution") or {}).get("available")
        ]
        by_date: dict[str, list[float]] = defaultdict(list)
        for item in items:
            outcome = item["horizons"][str(horizon)]
            value = outcome.get("market_excess_return_percent")
            if outcome.get("matured") and value is not None:
                by_date[item["signal_date"]].append(float(value))
        date_means = [mean(values) for values in by_date.values()]
        summary[str(horizon)] = {
            "matured_items": len(matured),
            "pending_or_missing_items": len(rows) - len(matured),
            "unique_signal_dates": len({item["signal_date"] for item in items
                                         if item["horizons"][str(horizon)].get("matured")}),
            "average_return_percent": _mean(row.get("return_percent") for row in matured),
            "median_return_percent": _median(row.get("return_percent") for row in matured),
            "positive_return_rate_percent": (
                round(sum(float(row["return_percent"]) > 0 for row in matured) / len(matured) * 100, 2)
                if matured else None
            ),
            "average_market_excess_return_percent": _mean(
                row.get("market_excess_return_percent") for row in matured
            ),
            "signal_date_equal_weighted_market_excess_percent": _mean(date_means),
            "positive_market_excess_rate_percent": (
                round(sum(float(row["market_excess_return_percent"]) > 0
                          for row in matured if row.get("market_excess_return_percent") is not None)
                      / sum(row.get("market_excess_return_percent") is not None for row in matured) * 100, 2)
                if any(row.get("market_excess_return_percent") is not None for row in matured) else None
            ),
            "average_industry_excess_return_percent": _mean(
                row.get("industry_excess_return_percent") for row in matured
            ),
            "average_max_drawdown_percent": _mean(
                row.get("max_drawdown_percent") for row in matured
            ),
            "executable_items": len(executions),
            "average_executable_gross_return_percent": _mean(
                row.get("gross_return_percent") for row in executions
            ),
            "average_executable_net_return_percent": _mean(
                row.get("net_return_percent") for row in executions
            ),
            "average_executable_market_excess_percent": _mean(
                row.get("market_excess_after_cost_percent") for row in executions
            ),
        }
    return summary


def _breakdown(items: list[dict], horizons: tuple[int, ...], field: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[str(item.get(field) or "unknown")].append(item)
    return {key: _summarize(rows, horizons) for key, rows in sorted(groups.items())}


def _effectiveness_assessment(
    summary: dict,
    rank_breakdown: dict,
    horizons: tuple[int, ...],
    minimum_items: int,
    minimum_signal_dates: int,
) -> dict:
    eligible, supported = [], []
    details = []
    for horizon in horizons:
        key = str(horizon)
        row = summary[key]
        enough = (
            row["matured_items"] >= minimum_items
            and row["unique_signal_dates"] >= minimum_signal_dates
        )
        top = rank_breakdown.get("top_1_3", {}).get(key, {})
        rest = rank_breakdown.get("rank_4_plus", {}).get(key, {})
        top_advantage = None
        if (top.get("average_market_excess_return_percent") is not None
                and rest.get("average_market_excess_return_percent") is not None):
            top_advantage = round(
                top["average_market_excess_return_percent"]
                - rest["average_market_excess_return_percent"], 4
            )
        market_positive = (row["average_market_excess_return_percent"] or 0) > 0
        industry_value = row["average_industry_excess_return_percent"]
        industry_positive = industry_value is not None and industry_value > 0
        rank_order_positive = top_advantage is not None and top_advantage > 0
        if enough:
            eligible.append(key)
            if market_positive and industry_positive and rank_order_positive:
                supported.append(key)
        details.append({
            "horizon_sessions": horizon,
            "enough_samples": enough,
            "market_excess_positive": market_positive,
            "industry_excess_positive": industry_positive,
            "top_1_3_minus_rank_4_plus_market_excess_percent": top_advantage,
            "rank_order_positive": rank_order_positive,
        })
    if not eligible:
        verdict = "insufficient_data"
    elif len(supported) >= 2:
        verdict = "promising_not_yet_validated"
    elif supported:
        verdict = "mixed_evidence"
    else:
        verdict = "historical_evidence_does_not_support_ranking"
    return {
        "verdict": verdict,
        "eligible_horizons": eligible,
        "supported_horizons": supported,
        "minimum_items_per_horizon": minimum_items,
        "minimum_signal_dates_per_horizon": minimum_signal_dates,
        "criteria": (
            "positive market and industry excess plus Top 1-3 outperforming lower ranks "
            "on at least two adequately sampled horizons"
        ),
        "details": details,
        "formal_validation_allowed": False,
        "reason": "historical replay must agree with ongoing forward snapshots",
    }


def short_term_ranking_backtest(
    database: Database,
    *,
    start_date: str = "2023-04-01",
    end_date: str | None = None,
    frequency: str = "monthly",
    top_n: int = 10,
    minimum_full_factor_symbols: int = 50,
    require_complete_factor_coverage: bool = True,
    max_signal_dates: int = 120,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    minimum_evaluation_items: int = 30,
    minimum_evaluation_signal_dates: int = 6,
    commission_bps: float = 14.25,
    sell_tax_bps: float = 30.0,
    slippage_bps: float = 5.0,
) -> dict:
    """Replay the current ranking without using information from the future."""
    end_date = end_date or date.today().isoformat()
    if date.fromisoformat(start_date) > date.fromisoformat(end_date):
        raise ValueError("start_date must not be after end_date")
    if not 1 <= top_n <= 50:
        raise ValueError("top_n must be between 1 and 50")
    if max_signal_dates < 1:
        raise ValueError("max_signal_dates must be positive")
    if not horizons or any(value < 1 or value > 60 for value in horizons):
        raise ValueError("horizons must contain session counts between 1 and 60")
    if any(value < 0 or value > 100 for value in (
        commission_bps, sell_tax_bps, slippage_bps,
    )):
        raise ValueError("execution cost assumptions must be between 0 and 100 bps")

    signal_dates, date_selection = _select_signal_dates(
        database, start_date, end_date, frequency, max_signal_dates
    )
    accepted_runs, skipped_dates = [], []
    audit_records = []
    coverage_rows = []
    for signal_date in signal_dates:
        coverage = _factor_coverage_as_of(database, signal_date)
        coverage_rows.append(coverage)
        full_ready = coverage["total"]["full_factor_ready_symbols"]
        if require_complete_factor_coverage and full_ready < minimum_full_factor_symbols:
            skipped_dates.append({
                "signal_date": signal_date,
                "reason": "insufficient_full_factor_coverage",
                "full_factor_ready_symbols": full_ready,
                "minimum_required": minimum_full_factor_symbols,
            })
            continue
        context = _market_context_as_of(database, signal_date)
        if not context:
            skipped_dates.append({"signal_date": signal_date, "reason": "missing_market_context"})
            continue
        result = build_short_term_decisions(
            database, context, date.fromisoformat(signal_date), top_n,
            historical_replay=True,
        )
        rankings = (result.get("attention_rankings") or [])[:top_n]
        if result.get("signal_date") != signal_date:
            skipped_dates.append({
                "signal_date": signal_date,
                "reason": "stock_market_dates_not_aligned",
                "ranking_signal_date": result.get("signal_date"),
            })
            continue
        if len(rankings) < top_n:
            skipped_dates.append({
                "signal_date": signal_date,
                "reason": "incomplete_top_n",
                "ranking_items": len(rankings),
                "required_items": top_n,
                "candidate_universe_counts": result.get("candidate_universe_counts") or {},
            })
            continue
        for rank, item in enumerate(rankings, 1):
            audit_records.append({
                "symbol": item.get("symbol"),
                "decision_date": signal_date,
                "available_at": _audit_available_at(item, signal_date),
            })
        accepted_runs.append({
            "signal_date": signal_date,
            "market_mode": result.get("market_mode"),
            "market_close": context["index_close"],
            "candidate_universe_counts": result.get("candidate_universe_counts") or {},
            "rankings": rankings,
        })

    pit_audit = lookahead_audit(audit_records)
    with database.connect() as connection:
        market_calendar = [row[0] for row in connection.execute(
            "SELECT trade_date FROM market_index_snapshots ORDER BY trade_date"
        )]
        market_closes = {row[0]: float(row[1]) for row in connection.execute(
            "SELECT trade_date,close FROM market_index_snapshots"
        )}

    industries = {
        str(item.get("industry") or "未分類")
        for run in accepted_runs for item in run["rankings"]
    }
    price_map: dict[tuple[str, str], dict[str, dict[str, float]]] = defaultdict(dict)
    industry_members: dict[str, list[tuple[str, str]]] = defaultdict(list)
    if accepted_runs and industries:
        placeholders = ",".join("?" for _ in industries)
        first_signal = min(run["signal_date"] for run in accepted_runs)
        with database.connect() as connection:
            instruments = [dict(row) for row in connection.execute(
                f"""SELECT symbol,market,COALESCE(industry,'未分類') AS industry
                    FROM instruments WHERE COALESCE(industry,'未分類') IN ({placeholders})""",
                tuple(sorted(industries)),
            )]
            for instrument in instruments:
                industry_members[instrument["industry"]].append(
                    (instrument["symbol"], instrument["market"])
                )
            for row in connection.execute(
                f"""SELECT p.symbol,p.market,p.trade_date,p.open,p.close
                    FROM daily_prices p JOIN instruments i
                      ON i.symbol=p.symbol AND i.market=p.market
                    WHERE COALESCE(i.industry,'未分類') IN ({placeholders})
                      AND p.trade_date>=? ORDER BY p.symbol,p.market,p.trade_date""",
                (*tuple(sorted(industries)), first_signal),
            ):
                price_map[(row["symbol"], row["market"])][row["trade_date"]] = {
                    "open": float(row["open"]),
                    "close": float(row["close"]),
                }

    items = []
    for run in accepted_runs:
        signal_date = run["signal_date"]
        market_position = bisect_right(market_calendar, signal_date)
        for rank, ranking in enumerate(run["rankings"], 1):
            symbol = str(ranking.get("symbol"))
            market = str(ranking.get("market"))
            industry = str(ranking.get("industry") or "未分類")
            signal_close = float(ranking["close"])
            series = price_map.get((symbol, market), {})
            outcomes = {}
            for horizon in horizons:
                target_index = market_position + horizon - 1
                if target_index >= len(market_calendar):
                    outcomes[str(horizon)] = {
                        "matured": False, "reason": "horizon_not_yet_available",
                        "target_date": None,
                    }
                    continue
                target_date = market_calendar[target_index]
                path_dates = market_calendar[market_position:target_index + 1]
                path = [series.get(value) for value in path_dates]
                if any(value is None for value in path):
                    outcomes[str(horizon)] = {
                        "matured": False, "reason": "missing_exact_session_price",
                        "target_date": target_date,
                    }
                    continue
                closes = [float(value["close"]) for value in path if value is not None]
                stock_return = (closes[-1] / signal_close - 1) * 100
                market_target = market_closes.get(target_date)
                market_return = (
                    (market_target / float(run["market_close"]) - 1) * 100
                    if market_target is not None and run.get("market_close") else None
                )
                peer_returns = []
                for peer in industry_members.get(industry, []):
                    if peer == (symbol, market):
                        continue
                    peer_series = price_map.get(peer, {})
                    peer_start = (peer_series.get(signal_date) or {}).get("close")
                    peer_end = (peer_series.get(target_date) or {}).get("close")
                    if peer_start and peer_end:
                        peer_returns.append((peer_end / peer_start - 1) * 100)
                industry_return = (
                    median(peer_returns) if len(peer_returns) >= MIN_INDUSTRY_PEERS else None
                )
                entry_date = path_dates[0]
                entry_open = float(path[0]["open"])
                exit_close = closes[-1]
                execution = {"available": False, "reason": "invalid_execution_price"}
                if entry_open > 0 and exit_close > 0:
                    gross_return = (exit_close / entry_open - 1) * 100
                    buy_cash = entry_open * (1 + slippage_bps / 10_000) * (
                        1 + commission_bps / 10_000
                    )
                    sell_cash = exit_close * (1 - slippage_bps / 10_000) * (
                        1 - (commission_bps + sell_tax_bps) / 10_000
                    )
                    net_return = (sell_cash / buy_cash - 1) * 100
                    execution = {
                        "available": True,
                        "entry_date": entry_date,
                        "entry_open": round(entry_open, 4),
                        "exit_date": target_date,
                        "exit_close": round(exit_close, 4),
                        "gross_return_percent": round(gross_return, 4),
                        "net_return_percent": round(net_return, 4),
                        "transaction_cost_drag_percent": round(gross_return - net_return, 4),
                        "market_excess_after_cost_percent": (
                            round(net_return - market_return, 4)
                            if market_return is not None else None
                        ),
                    }
                outcomes[str(horizon)] = {
                    "matured": True,
                    "target_date": target_date,
                    "return_percent": round(stock_return, 4),
                    "market_return_percent": round(market_return, 4)
                        if market_return is not None else None,
                    "market_excess_return_percent": round(stock_return - market_return, 4)
                        if market_return is not None else None,
                    "industry_median_return_percent": round(industry_return, 4)
                        if industry_return is not None else None,
                    "industry_excess_return_percent": round(stock_return - industry_return, 4)
                        if industry_return is not None else None,
                    "industry_peer_count": len(peer_returns),
                    "max_drawdown_percent": round(min(
                        0.0,
                        min(value / signal_close - 1 for value in closes) * 100,
                    ), 4),
                    "max_runup_percent": round(max(
                        0.0,
                        max(value / signal_close - 1 for value in closes) * 100,
                    ), 4),
                    "execution": execution,
                }
            items.append({
                "signal_date": signal_date,
                "symbol": symbol,
                "market": market,
                "name": ranking.get("name"),
                "industry": industry,
                "rank": rank,
                "rank_bucket": "top_1_3" if rank <= 3 else "rank_4_plus",
                "attention_grade": ranking.get("attention_grade"),
                "attention_score": ranking.get("attention_score"),
                "operation_status": ranking.get("operation_status"),
                "market_mode": run.get("market_mode"),
                "signal_close": signal_close,
                "data_as_of": ranking.get("data_as_of") or {},
                "horizons": outcomes,
            })

    summary = _summarize(items, horizons)
    rank_breakdown = _breakdown(items, horizons, "rank_bucket")
    grade_breakdown = _breakdown(items, horizons, "attention_grade")
    operation_status_breakdown = _breakdown(items, horizons, "operation_status")
    assessment = _effectiveness_assessment(
        summary, rank_breakdown, horizons,
        minimum_evaluation_items, minimum_evaluation_signal_dates,
    )
    if pit_audit.get("status") != "passed":
        assessment = {
            **assessment,
            "verdict": "rejected_lookahead",
            "formal_validation_allowed": False,
            "reason": "point-in-time audit found future data",
        }

    return {
        "mode": "short_term_ranking_historical_replay",
        "backtest_version": BACKTEST_VERSION,
        "ranking_strategy_version": STRATEGY_VERSION,
        "requested_period": {"start": start_date, "end": end_date},
        "data_cutoff": _data_cutoff(database),
        "date_selection": date_selection,
        "coverage_policy": {
            "require_complete_factor_coverage": require_complete_factor_coverage,
            "minimum_full_factor_symbols": minimum_full_factor_symbols,
            "required_inputs": [
                "60 price sessions", "4 PIT financial periods", "cash flow",
                "valuation", "published monthly revenue", "5 institutional sessions",
            ],
        },
        "coverage_by_signal_date": coverage_rows,
        "accepted_signal_dates": [run["signal_date"] for run in accepted_runs],
        "skipped_signal_dates": skipped_dates,
        "accepted_runs": len(accepted_runs),
        "total_ranked_items": len(items),
        "horizons": summary,
        "rank_bucket_breakdown": rank_breakdown,
        "grade_breakdown": grade_breakdown,
        "operation_status_breakdown": operation_status_breakdown,
        "effectiveness_assessment": assessment,
        "lookahead_audit": pit_audit,
        "outcomes": items,
        "methodology": {
            "signal": "fixed v2.5 ranking formed after the signal-day close",
            "measurement": "close-to-close predictive return on exact future market sessions",
            "market_benchmark": "TAIEX close-to-close over the same sessions",
            "market_context": "stored historical score, or neutral 50 when that score was not captured",
            "industry_benchmark": "median return of at least three current-universe industry peers",
            "execution_price": "next-session open to horizon-session close",
            "transaction_costs_bps": {
                "commission_each_side": commission_bps,
                "sell_tax": sell_tax_bps,
                "slippage_each_side": slippage_bps,
            },
            "execution_benchmark": (
                "net stock return after costs minus the existing signal-close-to-horizon-close "
                "TAIEX proxy; index open is not stored"
            ),
            "historical_event_policy": "dividend/event blocker disabled without announcement timestamps",
        },
        "limitations": [
            "Current instrument and industry membership creates survivorship/classification bias.",
            "Most older index rows lack a stored market score and therefore replay with neutral score 50.",
            "Unadjusted corporate actions can distort price returns around ex-rights, splits, and reductions.",
            "Historical dividend/event blocking is disabled until announcement timestamps are stored.",
            "Next-open execution is a daily-OHLC proxy and cannot model intraday fill quality or limit-up access.",
            "The market benchmark lacks index open data, so cost-adjusted market excess remains a conservative proxy.",
            "Historical evidence cannot replace the immutable forward ranking snapshots now being collected.",
        ],
    }
