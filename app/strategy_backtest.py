from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from statistics import mean

from app.backtest import historical_backtest
from app.database import Database
from app.portfolio_engine import construct_portfolio, portfolio_period_return


def _period_metrics(outcomes: list[dict], benchmark_key: str = "benchmark_return_percent") -> dict:
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
        benchmark_return = float(row[benchmark_key]) / 100
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


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 8 or len(left) != len(right):
        return None
    left_centered = [item - mean(left) for item in left]
    right_centered = [item - mean(right) for item in right]
    denominator = (sum(item * item for item in left_centered) *
                   sum(item * item for item in right_centered)) ** .5
    return round(sum(a * b for a, b in zip(left_centered, right_centered)) / denominator, 4) if denominator else None


def _attribution_report(outcomes: list[dict]) -> dict:
    """Explain results without changing signals or optimising parameters.

    Position contribution is the realised return multiplied by its target
    weight.  It therefore remains comparable across months with different cash
    allocations and cannot be mistaken for an unweighted stock average.
    """
    regime_rows: dict[str, list[dict]] = defaultdict(list)
    industries: dict[str, dict] = {}
    stocks: dict[str, dict] = {}
    factor_samples: dict[str, tuple[list[float], list[float]]] = {}
    for period in outcomes:
        cash = float(period.get("cash_percent") or 0)
        regime = "defensive" if cash >= 60 else "bullish" if cash <= 20 else "neutral"
        regime_rows[regime].append(period)
        for allocation in period.get("allocations", []):
            weight = float(allocation.get("target_weight_percent") or 0) / 100
            realised = float(allocation.get("return_percent") or 0)
            contribution = weight * realised
            for bucket, label in ((industries, allocation.get("industry") or "unknown"),
                                  (stocks, allocation.get("symbol") or "unknown")):
                row = bucket.setdefault(label, {"label": label, "positions": 0,
                                                "weight_sum_percent": 0.0,
                                                "contribution_percent": 0.0,
                                                "returns": []})
                row["positions"] += 1
                row["weight_sum_percent"] += weight * 100
                row["contribution_percent"] += contribution
                row["returns"].append(realised)
            for factor, score in (allocation.get("factors") or {}).items():
                if score is None:
                    continue
                values, returns = factor_samples.setdefault(factor, ([], []))
                values.append(float(score))
                returns.append(realised)

    def compact(rows: dict[str, dict]) -> list[dict]:
        return sorted(({"label": row["label"], "positions": row["positions"],
                        "average_weight_percent": round(row["weight_sum_percent"] / row["positions"], 4),
                        "average_return_percent": round(mean(row["returns"]), 4),
                        "contribution_percent": round(row["contribution_percent"], 4)}
                       for row in rows.values()), key=lambda row: row["contribution_percent"], reverse=True)

    by_regime = []
    for regime, rows in sorted(regime_rows.items()):
        metrics = _period_metrics(rows, "allocation_matched_benchmark_return_percent")
        by_regime.append({"regime": regime, **metrics,
                          "average_cash_percent": round(mean(float(row["cash_percent"]) for row in rows), 4)})
    factor_correlations = [{"factor": factor, "sample_size": len(values),
                            "score_return_correlation": _correlation(values, returns)}
                           for factor, (values, returns) in sorted(factor_samples.items())]
    return {"by_market_regime": by_regime, "by_industry": compact(industries),
            "by_stock": compact(stocks), "factor_score_return_correlation": factor_correlations,
            "methodology": "Industry and stock contribution use target weight × realised total return. Factor correlation is descriptive only; it is not evidence of causality or a parameter-selection rule."}


def strategy_walk_forward_backtest(
    database: Database, min_score: float = 65, top_n: int = 10,
    commission_bps: float = 14.25, sell_tax_bps: float = 30, slippage_bps: float = 5,
    start_date: str | None = None, end_date: str | None = None,
    out_of_sample_start: str | None = None, min_turnover: float = 10_000_000,
    single_stock_limit_percent: float = 10, industry_limit_percent: float = 25,
    research_weights: dict[str, float] | None = None,
) -> dict:
    """Monthly point-in-time portfolio simulation using official TAIEX closes."""
    base = historical_backtest(database, horizon=20, min_score=min_score, top_n=top_n,
                               start_date=start_date, end_date=end_date,
                               min_turnover=min_turnover, research_weights=research_weights)
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
        requested = grouped[current][:top_n]
        allocation = construct_portfolio(
            requested, max_total_exposure_percent=(1 - cash) * 100,
            single_stock_limit_percent=single_stock_limit_percent,
            industry_limit_percent=industry_limit_percent,
        )
        selected = allocation["allocations"]
        benchmark_return = index_by_date[following] / index_by_date[current] - 1
        period = portfolio_period_return(
            selected, commission_bps=commission_bps, sell_tax_bps=sell_tax_bps,
            slippage_bps=slippage_bps,
        )
        portfolio_return = period["net_return_percent"] / 100
        allocation_matched_benchmark_return = (
            period["invested_percent"] / 100 * benchmark_return
            - period["cost_percent"] / 100
        )
        equity *= 1 + portfolio_return
        benchmark *= 1 + benchmark_return
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
        returns.append(portfolio_return)
        outcomes.append({"date": current, "next_date": following, "cash_percent": allocation["cash_percent"],
                         "selected": len(selected), "strategy_return_percent": portfolio_return * 100,
                         "benchmark_return_percent": benchmark_return * 100,
                         "allocation_matched_benchmark_return_percent": allocation_matched_benchmark_return * 100,
                         "gross_return_percent": period["gross_return_percent"],
                         "transaction_cost_percent": period["cost_percent"],
                         "allocations": selected, "rejected": allocation["rejected"],
                         "constraints": allocation["constraints"],
                         "equity": equity, "benchmark_equity": benchmark})
    all_metrics = _period_metrics(outcomes)
    allocation_matched = _period_metrics(outcomes, "allocation_matched_benchmark_return_percent")
    in_sample = out_of_sample = None
    if out_of_sample_start:
        in_sample = _period_metrics([row for row in outcomes if row["date"] < out_of_sample_start])
        out_of_sample = _period_metrics([row for row in outcomes if row["date"] >= out_of_sample_start])
        in_sample_allocation_matched = _period_metrics(
            [row for row in outcomes if row["date"] < out_of_sample_start],
            "allocation_matched_benchmark_return_percent",
        )
        out_of_sample_allocation_matched = _period_metrics(
            [row for row in outcomes if row["date"] >= out_of_sample_start],
            "allocation_matched_benchmark_return_percent",
        )
    else:
        in_sample_allocation_matched = out_of_sample_allocation_matched = None
    attribution = _attribution_report(outcomes)
    return {"mode": "strategy_backtest", **all_metrics, "top_n": top_n,
            "min_score": min_score, "start_date": start_date, "end_date": end_date,
            "out_of_sample_start": out_of_sample_start,
            "in_sample": in_sample, "out_of_sample": out_of_sample,
            "allocation_matched_benchmark": allocation_matched,
            "in_sample_allocation_matched_benchmark": in_sample_allocation_matched,
            "out_of_sample_allocation_matched_benchmark": out_of_sample_allocation_matched,
            "final_equity": equity, "benchmark_equity": benchmark,
            "transaction_cost_assumption_bps": commission_bps + sell_tax_bps / 2 + slippage_bps * 2,
            "slippage_bps_per_side": slippage_bps,
            "minimum_daily_turnover": min_turnover,
            "research_weights": base["research_weights"],
            "portfolio_constraints": {"single_stock_limit_percent": single_stock_limit_percent,
                                        "industry_limit_percent": industry_limit_percent},
            "attribution": attribution,
            "outcomes": outcomes[-300:],
            "audit": base.get("audit", {}),
            "limitations": ["Monthly rebalance proxy; cash and stock dividends are included, but reductions, splits and delisted securities are not fully modelled.",
                            "Uses official TAIEX closes and conservative reporting lags. Full-investment TAIEX and allocation-matched TAIEX are both shown; selection skill should be judged against the latter.",
                            "Minimum daily turnover filters illiquid entries; slippage is a fixed proxy, not an order-book simulation.",
                            "Out-of-sample results only validate a pre-specified split; do not choose the split after seeing returns."]}
