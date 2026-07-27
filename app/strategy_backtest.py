from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from statistics import mean

from app.backtest import historical_backtest
from app.database import Database


def _period_metrics(outcomes: list[dict]) -> dict:
    """Summarise a contiguous period without carrying equity across a split."""
    if not outcomes:
        return {"periods": 0, "total_return_percent": None,
                "benchmark_total_return_percent": None, "excess_return_percent": None,
                "max_drawdown_percent": None, "monthly_volatility_percent": None}
    equity = benchmark = peak = 1.0
    returns = []
    drawdown = 0.0
    for row in outcomes:
        strategy_return = float(row["strategy_return_percent"]) / 100
        benchmark_return = float(row["benchmark_return_percent"]) / 100
        equity *= 1 + strategy_return
        benchmark *= 1 + benchmark_return
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
        returns.append(strategy_return)
    volatility = (mean((item - mean(returns)) ** 2 for item in returns) ** .5
                  if len(returns) > 1 else None)
    return {"periods": len(outcomes), "total_return_percent": round((equity - 1) * 100, 4),
            "benchmark_total_return_percent": round((benchmark - 1) * 100, 4),
            "excess_return_percent": round((equity - benchmark) * 100, 4),
            "max_drawdown_percent": round(drawdown * 100, 4),
            "monthly_volatility_percent": round(volatility * 100, 4) if volatility is not None else None}


def strategy_walk_forward_backtest(
    database: Database, min_score: float = 65, top_n: int = 10,
    commission_bps: float = 14.25, sell_tax_bps: float = 30, slippage_bps: float = 5,
    start_date: str | None = None, end_date: str | None = None,
    out_of_sample_start: str | None = None, min_turnover: float = 10_000_000,
) -> dict:
    """Monthly point-in-time portfolio simulation using official TAIEX closes."""
    base = historical_backtest(database, horizon=20, min_score=min_score, top_n=top_n,
                               start_date=start_date, end_date=end_date,
                               min_turnover=min_turnover)
    with database.connect() as connection:
        index_rows = [dict(row) for row in connection.execute(
            "SELECT trade_date,close FROM market_index_snapshots ORDER BY trade_date"
        )]
    if len(index_rows) < 61:
        return {"mode": "strategy_backtest", "periods": 0,
                "out_of_sample_start": out_of_sample_start,
                "in_sample": None, "out_of_sample": None,
                "limitations": ["market history unavailable"], "outcomes": []}
    index_by_date = {row["trade_date"]: float(row["close"]) for row in index_rows}
    index_dates = [row["trade_date"] for row in index_rows]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in base["outcomes"]:
        grouped[row["snapshot_date"]].append(row)
    equity = benchmark = peak = 1.0
    max_drawdown = 0.0
    outcomes, returns = [], []
    dates = sorted(grouped)
    for current, following in zip(dates, dates[1:]):
        position = bisect_right(index_dates, current) - 1
        if position < 60 or current not in index_by_date or following not in index_by_date:
            continue
        window = [index_by_date[item] for item in index_dates[position - 60:position + 1]]
        cash = .60 if window[-1] < mean(window) else .20 if window[-1] >= mean(window[-20:]) else .30
        selected = grouped[current][:top_n]
        stock_return = mean(row["return_percent"] for row in selected) / 100 if selected else 0.0
        benchmark_return = index_by_date[following] / index_by_date[current] - 1
        costs = (1 - cash) * (commission_bps + sell_tax_bps / 2 + slippage_bps * 2) / 10_000
        portfolio_return = (1 - cash) * stock_return - costs
        equity *= 1 + portfolio_return
        benchmark *= 1 + benchmark_return
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
        returns.append(portfolio_return)
        outcomes.append({"date": current, "next_date": following, "cash_percent": cash * 100,
                         "selected": len(selected), "strategy_return_percent": portfolio_return * 100,
                         "benchmark_return_percent": benchmark_return * 100,
                         "equity": equity, "benchmark_equity": benchmark})
    all_metrics = _period_metrics(outcomes)
    in_sample = out_of_sample = None
    if out_of_sample_start:
        in_sample = _period_metrics([row for row in outcomes if row["date"] < out_of_sample_start])
        out_of_sample = _period_metrics([row for row in outcomes if row["date"] >= out_of_sample_start])
    return {"mode": "strategy_backtest", **all_metrics, "top_n": top_n,
            "min_score": min_score, "start_date": start_date, "end_date": end_date,
            "out_of_sample_start": out_of_sample_start,
            "in_sample": in_sample, "out_of_sample": out_of_sample,
            "final_equity": equity, "benchmark_equity": benchmark,
            "transaction_cost_assumption_bps": commission_bps + sell_tax_bps / 2 + slippage_bps * 2,
            "slippage_bps_per_side": slippage_bps,
            "minimum_daily_turnover": min_turnover,
            "outcomes": outcomes[-300:],
            "audit": base.get("audit", {}),
            "limitations": ["Monthly rebalance proxy; cash and stock dividends are included, but reductions, splits and delisted securities are not fully modelled.",
                            "Uses official TAIEX closes and conservative reporting lags.",
                            "Minimum daily turnover filters illiquid entries; slippage is a fixed proxy, not an order-book simulation.",
                            "Out-of-sample results only validate a pre-specified split; do not choose the split after seeing returns."]}
