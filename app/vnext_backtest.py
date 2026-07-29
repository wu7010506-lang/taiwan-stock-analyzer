from __future__ import annotations

import json
from bisect import bisect_right
from datetime import date
from statistics import mean

from app.database import Database
from app.point_in_time import POINT_IN_TIME_POLICY
from app.vnext_model import recommend_vnext_stocks


def _monthly_dates(dates: list[str], start: str | None, end: str | None) -> list[str]:
    selected = [value for value in dates if (not start or value >= start) and (not end or value <= end)]
    months: dict[str, str] = {}
    for value in selected:
        months[value[:7]] = value
    return list(months.values())


def _context_as_of(database: Database, as_of: str) -> dict:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT trade_date,market_score,regime FROM market_index_snapshots
               WHERE trade_date<=? ORDER BY trade_date DESC LIMIT 1""", (as_of,)
        ).fetchone()
    if not row:
        return {"market_score": 50, "overheat_score": 0, "regime": "unknown",
                "historical_context_available": False}
    return {"market_score": row["market_score"] if row["market_score"] is not None else 50,
            "overheat_score": 0, "regime": row["regime"] or "unknown",
            "historical_context_available": True, "as_of": row["trade_date"]}


def vnext_walk_forward_backtest(
    database: Database, horizon: int = 20, top_n: int = 10,
    commission_bps: float = 14.25, sell_tax_bps: float = 30, slippage_bps: float = 5,
    min_turnover: float = 10_000_000, start_date: str | None = None,
    end_date: str | None = None, embargo_sessions: int = 7,
) -> dict:
    """Monthly vNext walk-forward simulation with next-session execution.

    Signals use only data available at the signal close under POINT_IN_TIME_POLICY;
    future prices are used solely to calculate the realised holding-period outcome.
    """
    with database.connect() as connection:
        prices = [dict(row) for row in connection.execute(
            """SELECT symbol,market,trade_date,close,volume FROM daily_prices
               ORDER BY symbol,trade_date"""
        )]
        dividends = [dict(row) for row in connection.execute(
            """SELECT symbol,ex_date,cash_dividend FROM dividend_events
               WHERE cash_dividend IS NOT NULL ORDER BY symbol,ex_date"""
        )]
    by_symbol: dict[str, list[dict]] = {}
    for row in prices:
        by_symbol.setdefault(row["symbol"], []).append(row)
    dividend_by_symbol: dict[str, list[dict]] = {}
    for row in dividends:
        dividend_by_symbol.setdefault(row["symbol"], []).append(row)
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
                "selected": 0, "liquidity_excluded": 0,
                "historical_context_available": context["historical_context_available"]}
        for rank, candidate in enumerate(result["recommendations"][:top_n], 1):
            series = by_symbol.get(candidate["symbol"], [])
            dates = [row["trade_date"] for row in series]
            entry_index = bisect_right(dates, signal_date)
            exit_index = entry_index + horizon - 1
            if entry_index >= len(series) or exit_index >= len(series):
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
                             "net_return_percent": round(net_return, 4)})
            fold["selected"] += 1
        folds.append(fold)
        last_signal_index = signal_index
    returns = [row["net_return_percent"] for row in outcomes]
    payload = {"mode": "vnext_walk_forward", "model": "vnext", "horizon": horizon,
               "top_n": top_n, "start_date": start_date, "end_date": end_date,
               "signals": len(folds), "purged_signals": purged_signals,
               "matured_positions": len(outcomes),
               "average_net_return_percent": round(mean(returns), 4) if returns else None,
               "win_rate_percent": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
               "transaction_costs": {"commission_bps_per_side": commission_bps,
                   "sell_tax_bps": sell_tax_bps, "slippage_bps_per_side": slippage_bps},
               "minimum_daily_turnover": min_turnover, "embargo_sessions": embargo_sessions,
               "point_in_time_policy": POINT_IN_TIME_POLICY, "folds": folds,
               "outcomes": outcomes[-300:],
               "limitations": ["Financial and revenue publication timing uses conservative calendar-lag proxies until source announcement timestamps are stored.",
                   "Cash dividends are included; stock dividends, delistings, suspensions, reductions and survivorship bias are not fully modelled.",
                   "Historical market context is used only when an archived index snapshot exists; otherwise it is neutral and disclosed.",
                   "Walk-forward simulation is historical research, not a guarantee of future investment results."]}
    run_id = database.save_vnext_backtest_run(
        start_date or (folds[0]["signal_date"] if folds else ""), end_date or (folds[-1]["signal_date"] if folds else ""),
        json.dumps({key: payload[key] for key in ("horizon", "top_n", "start_date", "end_date", "embargo_sessions")}),
        json.dumps(payload, ensure_ascii=False),
    )
    return {**payload, "run_id": run_id}
