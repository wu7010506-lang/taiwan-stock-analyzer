from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date, datetime
from statistics import mean

from app.database import Database
from app.point_in_time import POINT_IN_TIME_POLICY
from app.portfolio_engine import simulate_fixed_capital_trades
from app.technical_timing import assess_technical_timing
from app.vnext_model import recommend_vnext_stocks


def _monthly_dates(dates: list[str], start: str | None, end: str | None) -> list[str]:
    selected = [value for value in dates if (not start or value >= start) and (not end or value <= end)]
    months: dict[str, str] = {}
    for value in selected:
        months[value[:7]] = value
    return list(months.values())


def _context_as_of(database: Database, as_of: str) -> dict:
    with database.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT trade_date,close,market_score,overheat_score,regime
               FROM (SELECT trade_date,close,market_score,overheat_score,regime
                     FROM market_index_snapshots WHERE trade_date<=?
                     ORDER BY trade_date DESC LIMIT 21)
               ORDER BY trade_date""", (as_of,)
        )]
    if not rows:
        return {"market_score": 50, "overheat_score": 0, "regime": "unknown",
                "historical_context_available": False}
    row = rows[-1]
    index_return_20 = None
    if len(rows) >= 21 and rows[0].get("close") and row.get("close"):
        index_return_20 = round((float(row["close"]) / float(rows[0]["close"]) - 1) * 100, 6)
    return {"market_score": row["market_score"] if row["market_score"] is not None else 50,
            "overheat_score": row["overheat_score"] if row["overheat_score"] is not None else 0,
            "regime": row["regime"] or "unknown",
            "historical_context_available": True,
            "historical_overheat_available": row["overheat_score"] is not None,
            "index_change_20d": index_return_20, "as_of": row["trade_date"]}


def vnext_walk_forward_backtest(
    database: Database, horizon: int = 20, top_n: int = 10,
    commission_bps: float = 14.25, sell_tax_bps: float = 30, slippage_bps: float = 5,
    min_turnover: float = 10_000_000, start_date: str | None = None,
    end_date: str | None = None, embargo_sessions: int = 7,
    max_total_exposure_percent: float = 80, single_stock_limit_percent: float = 10,
    industry_limit_percent: float = 25, technical_timing: bool = False,
) -> dict:
    """Monthly vNext walk-forward simulation with next-session execution.

    Signals use only data available at the signal close under POINT_IN_TIME_POLICY;
    future prices are used solely to calculate the realised holding-period outcome.
    """
    parameters = {"method_version": "pit-vnext-coverage-v2", "horizon": horizon, "top_n": top_n, "start_date": start_date,
                  "end_date": end_date, "embargo_sessions": embargo_sessions,
                  "max_total_exposure_percent": max_total_exposure_percent,
                  "single_stock_limit_percent": single_stock_limit_percent,
                  "industry_limit_percent": industry_limit_percent,
                  "technical_timing": technical_timing,
                  "commission_bps": commission_bps, "sell_tax_bps": sell_tax_bps,
                  "slippage_bps": slippage_bps, "min_turnover": min_turnover}
    parameters_json = json.dumps(parameters, sort_keys=True)
    cached = database.get_recent_vnext_backtest_run(parameters_json)
    if cached:
        payload = json.loads(cached["result_json"])
        return {**payload, "run_id": cached["id"], "cache_hit": True}

    started_at = datetime.now().isoformat(timespec="seconds")
    with database.connect() as connection:
        prices = [dict(row) for row in connection.execute(
            """SELECT symbol,market,trade_date,open,high,low,close,volume FROM daily_prices
               ORDER BY symbol,trade_date"""
        )]
        dividends = [dict(row) for row in connection.execute(
            """SELECT symbol,ex_date,cash_dividend FROM dividend_events
               WHERE cash_dividend IS NOT NULL ORDER BY symbol,ex_date"""
        )]
        instruments = [dict(row) for row in connection.execute(
            "SELECT symbol, industry FROM instruments"
        )]
    by_symbol: dict[str, list[dict]] = {}
    for row in prices:
        by_symbol.setdefault(row["symbol"], []).append(row)
    dividend_by_symbol: dict[str, list[dict]] = {}
    for row in dividends:
        dividend_by_symbol.setdefault(row["symbol"], []).append(row)
    industries = {row["symbol"]: row.get("industry") or "unknown" for row in instruments}
    calendar = sorted({row["trade_date"] for row in prices})
    outcomes, folds = [], []
    last_signal_index: int | None = None
    purged_signals = 0
    for signal_date in _monthly_dates(calendar, start_date, end_date):
        signal_index = bisect_right(calendar, signal_date) - 1
        if signal_index < 0 or signal_index + 1 >= len(calendar):
            continue
        # A labelled position occupies `horizon` sessions after its next-session
        # entry.  Do not let a following fold reuse that outcome window; this is
        # the conservative purge + embargo boundary for this no-training model.
        if last_signal_index is not None and signal_index <= last_signal_index + horizon + embargo_sessions:
            purged_signals += 1
            continue
        context = _context_as_of(database, signal_date)
        result = recommend_vnext_stocks(database, date.fromisoformat(signal_date), context, top_n)
        fold = {"signal_date": signal_date, "execution_rule": "next_available_session",
                "evaluated": result["universe_summary"]["evaluated"],
                "eligible": result["universe_summary"]["eligible"],
                "observation": result["universe_summary"].get("observation", 0),
                "insufficient_data": result["universe_summary"].get("insufficient_data", 0),
                "missing_summary": result.get("missing_summary", {}),
                "selected": 0, "liquidity_excluded": 0, "technical_excluded": 0,
                "historical_context_available": context["historical_context_available"],
                "historical_overheat_available": context.get("historical_overheat_available", False)}
        for rank, candidate in enumerate(result["recommendations"][:top_n], 1):
            series = by_symbol.get(candidate["symbol"], [])
            dates = [row["trade_date"] for row in series]
            entry_index = bisect_right(dates, signal_date)
            exit_index = entry_index + horizon - 1
            if entry_index >= len(series) or exit_index >= len(series):
                continue
            timing = assess_technical_timing(series[:bisect_right(dates, signal_date)], context)
            if technical_timing and timing["signal"] != "favorable":
                fold["technical_excluded"] += 1
                continue
            entry, exit_row = series[entry_index], series[exit_index]
            turnover = float(entry["close"]) * float(entry.get("volume") or 0)
            if turnover < min_turnover:
                fold["liquidity_excluded"] += 1
                continue
            cash = sum(float(row.get("cash_dividend") or 0) for row in dividend_by_symbol.get(candidate["symbol"], [])
                       if entry["trade_date"] < row["ex_date"] <= exit_row["trade_date"])
            buy_cost = (commission_bps + slippage_bps) / 10_000
            sell_cost = (commission_bps + sell_tax_bps + slippage_bps) / 10_000
            net_return = (((float(exit_row["close"]) + cash) * (1 - sell_cost)) /
                          (float(entry["close"]) * (1 + buy_cost)) - 1) * 100
            outcomes.append({"signal_date": signal_date, "entry_date": entry["trade_date"],
                             "exit_date": exit_row["trade_date"], "symbol": candidate["symbol"],
                             "rank": rank, "score": candidate["value_score"],
                             "entry_close": entry["close"], "exit_close": exit_row["close"],
                             "cash_dividend": cash, "turnover": turnover,
                             "technical_timing": timing if technical_timing else None,
                             "industry": industries.get(candidate["symbol"], "unknown"),
                             "net_return_percent": round(net_return, 4)})
            fold["selected"] += 1
        folds.append(fold)
        last_signal_index = signal_index
    returns = [row["net_return_percent"] for row in outcomes]
    missing_summary: dict[str, int] = {}
    for fold in folds:
        for name, count in fold["missing_summary"].items():
            missing_summary[name] = missing_summary.get(name, 0) + count
    eligibility_coverage = {
        "folds_with_eligible_stocks": sum(fold["eligible"] > 0 for fold in folds),
        "total_eligible_across_folds": sum(fold["eligible"] for fold in folds),
        "missing_summary": missing_summary,
        "status": "sufficient" if outcomes else "insufficient_historical_coverage",
    }
    portfolio = simulate_fixed_capital_trades(
        outcomes, max_total_exposure_percent=max_total_exposure_percent,
        single_stock_limit_percent=single_stock_limit_percent,
        industry_limit_percent=industry_limit_percent,
    )
    payload = {"mode": "vnext_walk_forward", "model": "vnext",
               "technical_timing": technical_timing, "horizon": horizon,
               "top_n": top_n, "start_date": start_date, "end_date": end_date,
               "signals": len(folds), "purged_signals": purged_signals,
               "matured_positions": len(outcomes),
               "average_net_return_percent": round(mean(returns), 4) if returns else None,
               "win_rate_percent": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
               "transaction_costs": {"commission_bps_per_side": commission_bps,
                   "sell_tax_bps": sell_tax_bps, "slippage_bps_per_side": slippage_bps},
               "minimum_daily_turnover": min_turnover, "embargo_sessions": embargo_sessions,
               "technical_excluded_positions": sum(fold["technical_excluded"] for fold in folds),
               "portfolio_simulation": portfolio,
               "eligibility_coverage": eligibility_coverage,
               "point_in_time_policy": POINT_IN_TIME_POLICY, "folds": folds,
               "outcomes": outcomes[-300:],
               "limitations": ["The shared-capital simulation books open trades at cost until exit, so it does not claim an intraday marked-to-market drawdown.",
                   "Financial and revenue publication timing uses conservative calendar-lag proxies until source announcement timestamps are stored.",
                   "Cash dividends are included; stock dividends, delistings, suspensions, reductions and survivorship bias are not fully modelled.",
                   "Historical market context is used only when an archived index snapshot exists; historical overheat is neutral when the older snapshot has no stored overheat score.",
                   "Walk-forward simulation is historical research, not a guarantee of future investment results."]}
    if technical_timing:
        payload["limitations"].append(
            "Technical filters are pre-specified research rules. Compare this result with the same run using technical_timing=false; do not infer causality from a small sample."
        )
    run_id = database.save_vnext_backtest_run(
        started_at, datetime.now().isoformat(timespec="seconds"), parameters_json,
        json.dumps(payload, ensure_ascii=False),
    )
    return {**payload, "run_id": run_id, "cache_hit": False}
