from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from statistics import mean

from app.backtest import historical_backtest
from app.database import Database


def strategy_walk_forward_backtest(
    database: Database, min_score: float = 65, top_n: int = 10,
    commission_bps: float = 14.25, sell_tax_bps: float = 30,
) -> dict:
    """Monthly point-in-time portfolio simulation using official TAIEX closes."""
    base = historical_backtest(database, horizon=20, min_score=min_score, top_n=top_n)
    with database.connect() as connection:
        index_rows = [dict(row) for row in connection.execute(
            "SELECT trade_date,close FROM market_index_snapshots ORDER BY trade_date"
        )]
    if len(index_rows) < 61:
        return {"mode": "strategy_backtest", "periods": 0,
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
        costs = (1 - cash) * (commission_bps + sell_tax_bps / 2) / 10_000
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
    volatility = (mean((value - mean(returns)) ** 2 for value in returns) ** .5
                  if len(returns) > 1 else None)
    return {"mode": "strategy_backtest", "periods": len(outcomes), "top_n": top_n,
            "min_score": min_score, "final_equity": equity, "benchmark_equity": benchmark,
            "total_return_percent": (equity - 1) * 100,
            "benchmark_total_return_percent": (benchmark - 1) * 100,
            "excess_return_percent": (equity - benchmark) * 100,
            "max_drawdown_percent": max_drawdown * 100,
            "monthly_volatility_percent": volatility * 100 if volatility is not None else None,
            "transaction_cost_assumption_bps": commission_bps + sell_tax_bps / 2,
            "outcomes": outcomes[-300:],
            "limitations": ["Monthly rebalance proxy; corporate actions and delisted securities are not yet modelled.",
                            "Uses official TAIEX closes and conservative reporting lags."]}
