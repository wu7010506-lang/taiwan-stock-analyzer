from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median

from app.database import Database
from app.evidence_model import build_evidence_from_rows
from app.historical_valuation import build_symbol_valuation_history


WEIGHTS = {
    "business_quality": 30, "cashflow_quality": 20, "durability": 15,
    "value": 15, "risk_resilience": 10, "growth_quality": 5, "market_fit": 5,
}


def _percentile(value: float | None, values: list[float], inverse: bool = False) -> float:
    if value is None or not values:
        return 50.0
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    rank = (below + max(equal - 1, 0) / 2) / max(len(values) - 1, 1) * 100
    return 100 - rank if inverse else rank


def _available_on(row: dict) -> date:
    statement = date.fromisoformat(str(row["statement_date"])[:10])
    # Conservative publication lag prevents a quarter from entering before investors saw it.
    return statement + timedelta(days=90 if int(row["fiscal_quarter"]) == 4 else 45)


def _monthly_dates(all_dates: list[str], start: str | None, end: str | None) -> list[str]:
    selected = [item for item in all_dates if (not start or item >= start) and (not end or item <= end)]
    months: dict[str, str] = {}
    for item in selected:
        months[item[:7]] = item
    return list(months.values())


def _score_cross_section(evidence: dict[str, dict], financials: dict[str, list[dict]],
                         prices: dict[str, list[dict]], as_of: str) -> list[dict]:
    eligible = {symbol: item for symbol, item in evidence.items() if item.get("evidence_ready")}
    fields = ("median_roe_annual", "median_operating_margin", "median_fcf_margin",
              "cash_conversion", "positive_fcf_ratio", "profitable_year_ratio",
              "positive_eps_year_ratio", "revenue_cagr_annual", "latest_debt_ratio",
              "margin_variation", "roe_variation")
    universes = {field: [float(item[field]) for item in eligible.values()
                         if item.get(field) is not None] for field in fields}
    results = []
    for symbol, item in eligible.items():
        if symbol not in prices or symbol not in financials:
            continue
        rank = lambda field, inverse=False: _percentile(item.get(field), universes[field], inverse)
        business = rank("median_roe_annual") * .45 + rank("median_operating_margin") * .30 + rank("profitable_year_ratio") * .25
        cashflow = rank("median_fcf_margin") * .35 + rank("cash_conversion") * .35 + rank("positive_fcf_ratio") * .30
        durability = rank("profitable_year_ratio") * .35 + rank("positive_eps_year_ratio") * .30 + rank("margin_variation", True) * .20 + rank("roe_variation", True) * .15
        risk = rank("latest_debt_ratio", True) * .45 + rank("margin_variation", True) * .20 + rank("roe_variation", True) * .10 + rank("positive_fcf_ratio") * .25
        growth = rank("revenue_cagr_annual") * .65 + rank("positive_fcf_ratio") * .35
        valuation = build_symbol_valuation_history(financials[symbol], prices[symbol])
        value = valuation.get("historical_value_score")
        if value is None:
            continue
        dimensions = {"business_quality": business, "cashflow_quality": cashflow,
                      "durability": durability, "value": value,
                      "risk_resilience": risk, "growth_quality": growth,
                      "market_fit": 50.0}
        score = sum(dimensions[key] * weight / 100 for key, weight in WEIGHTS.items())
        results.append({"symbol": symbol, "score": round(score, 1), "factors": dimensions,
                        "close": float(prices[symbol][-1]["close"]), "snapshot_date": as_of})
    return sorted(results, key=lambda row: row["score"], reverse=True)


def historical_backtest(database: Database, horizon: int = 20, min_score: float = 65,
                        top_n: int = 10, start_date: str | None = None,
                        end_date: str | None = None) -> dict:
    """Monthly walk-forward proxy using only statements available at each scoring date."""
    with database.connect() as connection:
        financial_rows = [dict(row) for row in connection.execute(
            "SELECT * FROM financial_snapshots WHERE statement_date IS NOT NULL ORDER BY symbol,fiscal_year,fiscal_quarter")]
        price_rows = [dict(row) for row in connection.execute(
            "SELECT symbol,market,trade_date,close FROM daily_prices ORDER BY symbol,trade_date")]
        names = {row["symbol"]: row["name"] for row in connection.execute("SELECT symbol,name FROM instruments")}
    full_prices: dict[str, list[dict]] = defaultdict(list)
    financial_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in price_rows:
        full_prices[row["symbol"]].append(row)
    for row in financial_rows:
        financial_by_symbol[row["symbol"]].append(row)
    calendar = sorted({row["trade_date"] for row in price_rows})
    scoring_dates = _monthly_dates(calendar, start_date, end_date)
    outcomes, evaluated_dates = [], []
    for as_of in scoring_dates:
        cutoff = date.fromisoformat(as_of)
        visible = [row for row in financial_rows if _available_on(row) <= cutoff]
        evidence = build_evidence_from_rows(visible)
        point_prices = {symbol: rows[:bisect_right([r["trade_date"] for r in rows], as_of)]
                        for symbol, rows in full_prices.items()}
        point_prices = {symbol: rows for symbol, rows in point_prices.items() if rows}
        candidates = _score_cross_section(
            evidence,
            {symbol: [row for row in rows if _available_on(row) <= cutoff]
             for symbol, rows in financial_by_symbol.items()},
            point_prices, as_of,
        )
        selected = [row for row in candidates if row["score"] >= min_score][:top_n]
        if candidates:
            evaluated_dates.append({"date": as_of, "eligible": len(candidates), "selected": len(selected)})
        for rank, row in enumerate(selected, 1):
            series = full_prices[row["symbol"]]
            dates = [item["trade_date"] for item in series]
            entry_index = bisect_left(dates, as_of)
            target = entry_index + horizon
            if entry_index >= len(series) or target >= len(series):
                continue
            entry = float(series[entry_index]["close"])
            future = series[entry_index + 1:target + 1]
            result_return = (float(series[target]["close"]) / entry - 1) * 100
            drawdown = min((float(item["close"]) / entry - 1) * 100 for item in future)
            outcomes.append({**row, "name": names.get(row["symbol"]), "rank": rank,
                             "return_percent": result_return,
                             "max_drawdown_percent": drawdown, "matured": True,
                             "excess_return_percent": None})
    returns = [row["return_percent"] for row in outcomes]
    drawdowns = [row["max_drawdown_percent"] for row in outcomes]
    unique_symbols = len({row["symbol"] for row in outcomes})
    return {"mode": "historical_backtest", "profile": "evidence_based", "horizon": horizon,
            "min_score": min_score, "top_n": top_n, "total_signals": len(outcomes),
            "matured_signals": len(outcomes), "pending_signals": 0,
            "win_rate_percent": sum(value > 0 for value in returns) / len(returns) * 100 if returns else None,
            "average_return_percent": mean(returns) if returns else None,
            "median_return_percent": median(returns) if returns else None,
            "average_excess_return_percent": None,
            "average_max_drawdown_percent": mean(drawdowns) if drawdowns else None,
            "scoring_dates": len(evaluated_dates), "unique_symbols": unique_symbols,
            "coverage": evaluated_dates, "outcomes": sorted(outcomes, key=lambda row: row["snapshot_date"], reverse=True)[:300],
            "limitations": ["財報採 Q1–Q3 延後 45 天、Q4 延後 90 天後才可用。",
                            "目前缺少完整歷史大盤序列，市場配適固定 50 分且不計超額報酬。",
                            "只納入具至少約兩年估值行情及完整五年財報的股票，未含交易成本與滑價。"]}
