from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from app.database import Database


def _percentile(value: float | None, history: list[float], inverse: bool = False) -> float | None:
    if value is None or not history:
        return None
    ordered = sorted(history)
    rank = bisect_right(ordered, value) / len(ordered) * 100
    return 100 - rank if inverse else rank


def _standalone(rows: list[dict], field: str) -> dict[tuple[int, int], float]:
    result = {}
    by_year: dict[int, dict[int, float]] = defaultdict(dict)
    for row in rows:
        value = row.get(field)
        if value is not None:
            by_year[int(row["fiscal_year"])][int(row["fiscal_quarter"])] = float(value)
    for year, quarters in by_year.items():
        for quarter in sorted(quarters):
            cumulative = quarters[quarter]
            previous = quarters.get(quarter - 1) if quarter > 1 else None
            result[(year, quarter)] = cumulative - previous if previous is not None else cumulative
    return result


def _quarterly(rows: list[dict], field: str) -> dict[tuple[int, int], float]:
    return {(int(row["fiscal_year"]), int(row["fiscal_quarter"])): float(row[field])
            for row in rows if row.get(field) is not None}


def build_symbol_valuation_history(financials: list[dict], prices: list[dict]) -> dict:
    if not financials or not prices:
        return {}
    rows = sorted((row for row in financials if row.get("statement_date")),
                  key=lambda row: (row["fiscal_year"], row["fiscal_quarter"]))
    # FinMind income-statement values are single-quarter values, while cash-flow
    # statements are cumulative from the start of each fiscal year.
    quarterly_eps = _quarterly(rows, "eps")
    quarterly_fcf = _standalone(rows, "free_cash_flow")
    statements = []
    for index, row in enumerate(rows):
        key = (int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        prior_keys = [(int(item["fiscal_year"]), int(item["fiscal_quarter"]))
                      for item in rows[:index + 1]][-4:]
        ttm_eps = (sum(quarterly_eps[item] for item in prior_keys)
                   if len(prior_keys) == 4 and all(item in quarterly_eps for item in prior_keys)
                   else None)
        ttm_fcf = (sum(quarterly_fcf[item] for item in prior_keys)
                   if len(prior_keys) == 4 and all(item in quarterly_fcf for item in prior_keys)
                   else None)
        share_capital = row.get("share_capital")
        shares = float(share_capital) / 10 if share_capital and share_capital > 0 else None
        # Prefer the source's reported per-share figure.  Balance-sheet values
        # are not consistently expressed in the same unit across providers,
        # while book_value_per_share is already unit-safe.
        bvps = row.get("book_value_per_share")
        if bvps is None and shares and row.get("equity") is not None:
            bvps = float(row["equity"]) / shares
        bvps = float(bvps) if bvps is not None else None
        statement_date = date.fromisoformat(row["statement_date"])
        lag = 90 if key[1] == 4 else 45
        statements.append({"available_date": statement_date + timedelta(days=lag),
                           "ttm_eps": ttm_eps, "ttm_fcf": ttm_fcf,
                           "shares": shares, "bvps": bvps})
    available_dates = [item["available_date"] for item in statements]
    series = []
    for price in sorted(prices, key=lambda item: item["trade_date"]):
        trade_date = date.fromisoformat(str(price["trade_date"])[:10])
        statement_index = bisect_right(available_dates, trade_date) - 1
        close = float(price["close"])
        if statement_index < 0 or close <= 0:
            continue
        statement = statements[statement_index]
        pe = (close / statement["ttm_eps"] if statement["ttm_eps"] and
              statement["ttm_eps"] > 0 else None)
        pb = close / statement["bvps"] if statement["bvps"] and statement["bvps"] > 0 else None
        earnings_yield = statement["ttm_eps"] / close * 100 if statement["ttm_eps"] else None
        fcf_yield = (statement["ttm_fcf"] / statement["shares"] / close * 100
                     if statement["ttm_fcf"] is not None and statement["shares"] else None)
        series.append({"date": trade_date.isoformat(), "close": close, "pe": pe, "pb": pb,
                       "earnings_yield": earnings_yield, "fcf_yield": fcf_yield})
    if not series:
        return {}
    latest = series[-1]
    histories = {key: [row[key] for row in series if row[key] is not None]
                 for key in ("pe", "pb", "earnings_yield", "fcf_yield")}
    scores = {
        "pe": _percentile(latest["pe"], histories["pe"], inverse=True),
        "pb": _percentile(latest["pb"], histories["pb"], inverse=True),
        "earnings_yield": _percentile(latest["earnings_yield"], histories["earnings_yield"]),
        "fcf_yield": _percentile(latest["fcf_yield"], histories["fcf_yield"]),
    }
    weights = {"pe": 40, "pb": 20, "fcf_yield": 25, "earnings_yield": 15}
    available = {key: value for key, value in scores.items() if value is not None}
    weight_sum = sum(weights[key] for key in available)
    # Roughly two trading years are required; shorter windows easily mistake a
    # temporary market regime for a company's normal valuation range.
    minimum_observations = 500
    reliable = len(series) >= minimum_observations
    score = (sum(value * weights[key] for key, value in available.items()) / weight_sum
             if weight_sum and reliable else None)
    return {"as_of": latest["date"], "observations": len(series),
            "history_start": series[0]["date"], "history_end": series[-1]["date"],
            "current_pe": latest["pe"], "current_pb": latest["pb"],
            "current_earnings_yield": latest["earnings_yield"],
            "current_fcf_yield": latest["fcf_yield"],
            "pe_cheapness_percentile": scores["pe"],
            "pb_cheapness_percentile": scores["pb"],
            "earnings_yield_percentile": scores["earnings_yield"],
            "fcf_yield_percentile": scores["fcf_yield"],
            "historical_value_score": score, "history_reliable": reliable,
            "minimum_observations": minimum_observations, "series": series}


def build_historical_valuations(database: Database) -> dict[str, dict]:
    with database.connect() as connection:
        financials = [dict(row) for row in connection.execute(
            """SELECT * FROM financial_snapshots WHERE statement_date IS NOT NULL
               ORDER BY symbol, fiscal_year, fiscal_quarter""")]
        prices = [dict(row) for row in connection.execute(
            """SELECT p.symbol, p.trade_date, p.close FROM daily_prices p
               WHERE p.trade_date >= date('now', '-5 years') ORDER BY p.symbol, p.trade_date""")]
    financial_by_symbol: dict[str, list[dict]] = defaultdict(list)
    price_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in financials:
        financial_by_symbol[row["symbol"]].append(row)
    for row in prices:
        price_by_symbol[row["symbol"]].append(row)
    return {symbol: result for symbol, rows in financial_by_symbol.items()
            if (result := build_symbol_valuation_history(rows, price_by_symbol[symbol]))}


def get_historical_valuation(database: Database, symbol: str, series_limit: int = 250) -> dict:
    result = build_historical_valuations(database).get(symbol, {})
    if result and len(result["series"]) > series_limit:
        result = {**result, "series": result["series"][-series_limit:]}
    return result
