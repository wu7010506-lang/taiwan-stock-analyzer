from __future__ import annotations

from statistics import mean, pstdev

from app.database import Database
from app.portfolio_engine import simulate_fixed_capital_trades


def _same_exposure_index_benchmark(database: Database, trades: list[dict], *,
                                   commission_bps: float, sell_tax_bps: float,
                                   slippage_bps: float, constraints: dict) -> dict:
    """Replay each accepted trade as TAIEX exposure over its identical holding window.

    The price index only supplies closes, so this is intentionally a close-to-close
    proxy and cannot substitute for a tradable ETF execution benchmark.  A missing
    date invalidates the aggregate rather than silently changing the exposure.
    """
    with database.connect() as connection:
        index = {row["trade_date"]: float(row["close"]) for row in connection.execute(
            "SELECT trade_date,close FROM market_index_snapshots ORDER BY trade_date")}
    buy_cost = (commission_bps + slippage_bps) / 10_000
    sell_cost = (commission_bps + sell_tax_bps + slippage_bps) / 10_000
    benchmark_trades = []
    for trade in trades:
        entry, exit_ = index.get(trade["entry_date"]), index.get(trade["exit_date"])
        if not entry or not exit_ or entry <= 0:
            continue
        benchmark_trades.append({**trade, "net_return_percent": round(
            ((exit_ * (1 - sell_cost)) / (entry * (1 + buy_cost)) - 1) * 100, 4)})
    required = len(trades)
    coverage = len(benchmark_trades) / required * 100 if required else 0.0
    if required == 0 or coverage < 95:
        return {"status": "insufficient_index_coverage", "required_trades": required,
                "matched_trades": len(benchmark_trades), "coverage_percent": round(coverage, 2),
                "limitation": "TAIEX close is missing for at least one material strategy holding window."}
    strategy = simulate_fixed_capital_trades(trades, **constraints)
    benchmark = simulate_fixed_capital_trades(benchmark_trades, **constraints)
    return {"status": "available_close_to_close_proxy", "required_trades": required,
            "matched_trades": len(benchmark_trades), "coverage_percent": round(coverage, 2),
            "strategy_total_return_percent": strategy["net_return_percent"],
            "benchmark_total_return_percent": benchmark["net_return_percent"],
            "excess_return_percent": round(strategy["net_return_percent"] - benchmark["net_return_percent"], 4),
            "strategy_simulation": strategy, "benchmark_simulation": benchmark,
            "limitation": "Same accepted trades, dates, capital limits and stated costs; TAIEX close-to-close proxy has no ETF open, spread or dividend execution."}


def _ema_series(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    value = mean(values[:period])
    result[period - 1] = value
    multiplier = 2 / (period + 1)
    for index in range(period, len(values)):
        value = (values[index] - value) * multiplier + value
        result[index] = value
    return result


def _rsi_series(values: list[float], period: int = 14) -> list[float | None]:
    changes = [0.0] + [current - previous for previous, current in zip(values, values[1:])]
    gains = _wilder([max(change, 0.0) for change in changes], period)
    losses = _wilder([max(-change, 0.0) for change in changes], period)
    return [100 if loss == 0 and gain else (100 - 100 / (1 + gain / loss))
            if gain is not None and loss is not None and loss else None
            for gain, loss in zip(gains, losses)]


def _bollinger(values: list[float], period: int = 20, deviation: float = 2) -> tuple[list[float | None], list[float | None]]:
    middle, lower = [None] * len(values), [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1:index + 1]
        average = mean(window)
        middle[index], lower[index] = average, average - deviation * pstdev(window)
    return middle, lower


def _wilder(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    value = mean(values[:period])
    result[period - 1] = value
    for index in range(period, len(values)):
        value = (value * (period - 1) + values[index]) / period
        result[index] = value
    return result


def _dmi_adx(rows: list[dict], period: int = 14) -> tuple[list[float | None], list[float | None], list[float | None], list[float | None]]:
    plus_dm, minus_dm, true_ranges = [0.0], [0.0], [0.0]
    for previous, current in zip(rows, rows[1:]):
        up = float(current["high"]) - float(previous["high"])
        down = float(previous["low"]) - float(current["low"])
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        true_ranges.append(max(float(current["high"]) - float(current["low"]),
                               abs(float(current["high"]) - float(previous["close"])),
                               abs(float(current["low"]) - float(previous["close"]))))
    atr, plus, minus = _wilder(true_ranges, period), _wilder(plus_dm, period), _wilder(minus_dm, period)
    plus_di = [100 * p / a if p is not None and a else None for p, a in zip(plus, atr)]
    minus_di = [100 * m / a if m is not None and a else None for m, a in zip(minus, atr)]
    dx = [100 * abs(p - m) / (p + m) if p is not None and m is not None and p + m else 0.0
          for p, m in zip(plus_di, minus_di)]
    return atr, plus_di, minus_di, _wilder(dx, period)


def ema_adx_atr_backtest(database: Database, *, fast_ema: int = 20, slow_ema: int = 100,
                         trend_ema: int = 200, exit_ema: int = 50, adx_threshold: float = 20,
                         initial_stop_atr: float = 2.5, trailing_stop_atr: float = 3,
                         commission_bps: float = 14.25, sell_tax_bps: float = 30,
                         slippage_bps: float = 5, min_turnover: float = 10_000_000,
                         max_total_exposure_percent: float = 80, single_stock_limit_percent: float = 10,
                         industry_limit_percent: float = 25, start_date: str | None = None,
                         end_date: str | None = None, out_of_sample_start: str | None = None) -> dict:
    """Predeclared long-only EMA/ADX trend study; signals execute next open."""
    with database.connect() as connection:
        instruments = {(row["symbol"], row["market"]): dict(row) for row in connection.execute("SELECT symbol,market,name,industry FROM instruments")}
        prices = [dict(row) for row in connection.execute("SELECT symbol,market,trade_date,open,high,low,close,volume FROM daily_prices ORDER BY symbol,market,trade_date")]
    series: dict[tuple[str, str], list[dict]] = {}
    for row in prices:
        series.setdefault((row["symbol"], row["market"]), []).append(row)
    trades = []
    for key, rows in series.items():
        last_index = max((index for index, row in enumerate(rows)
                          if not end_date or row["trade_date"] <= end_date), default=-1)
        if last_index <= trend_ema:
            continue
        closes = [float(row["close"]) for row in rows]
        fast, slow, trend, exit_line = (_ema_series(closes, value) for value in (fast_ema, slow_ema, trend_ema, exit_ema))
        atr, plus_di, minus_di, adx = _dmi_adx(rows)
        next_allowed = trend_ema
        for index in range(trend_ema, last_index):
            if index < next_allowed or None in (fast[index], slow[index], trend[index], atr[index], plus_di[index], minus_di[index], adx[index]):
                continue
            if (start_date and rows[index]["trade_date"] < start_date) or (end_date and rows[index]["trade_date"] > end_date):
                continue
            crossed = fast[index - 1] is not None and slow[index - 1] is not None and fast[index - 1] <= slow[index - 1] < fast[index]
            if not (crossed and closes[index] > trend[index] and plus_di[index] > minus_di[index] and adx[index] > adx_threshold):
                continue
            entry_index = index + 1
            if entry_index >= last_index:
                continue
            if float(rows[entry_index]["open"]) * float(rows[entry_index].get("volume") or 0) < min_turnover:
                continue
            entry = float(rows[entry_index]["open"]); stop = entry - initial_stop_atr * atr[index]; high_close = entry
            exit_index, exit_price, reason = last_index, float(rows[last_index]["close"]), "end_of_test" if end_date else "end_of_data"
            for candidate in range(entry_index, last_index + 1):
                high_close = max(high_close, float(rows[candidate]["close"]))
                trail = high_close - trailing_stop_atr * (atr[candidate] or atr[index])
                active_stop = max(stop, trail)
                if float(rows[candidate]["low"]) <= active_stop:
                    exit_index, exit_price, reason = candidate, min(float(rows[candidate]["open"]), active_stop), "atr_trailing_stop"
                    break
                if candidate > entry_index and ((fast[candidate] is not None and slow[candidate] is not None and fast[candidate] < slow[candidate]) or (exit_line[candidate] is not None and closes[candidate] < exit_line[candidate])):
                    exit_index, exit_price, reason = candidate, float(rows[candidate]["close"]), "trend_exit"
                    break
            buy_cost = (commission_bps + slippage_bps) / 10_000; sell_cost = (commission_bps + sell_tax_bps + slippage_bps) / 10_000
            instrument = instruments[key]
            trades.append({"symbol": key[0], "market": key[1], "name": instrument.get("name"), "industry": instrument.get("industry") or "unknown", "signal_date": rows[index]["trade_date"], "entry_date": rows[entry_index]["trade_date"], "exit_date": rows[exit_index]["trade_date"], "exit_reason": reason, "net_return_percent": round(((exit_price * (1 - sell_cost)) / (entry * (1 + buy_cost)) - 1) * 100, 4)})
            next_allowed = exit_index + 1
    returns = [row["net_return_percent"] for row in trades]
    constraints = {"max_total_exposure_percent": max_total_exposure_percent, "single_stock_limit_percent": single_stock_limit_percent, "industry_limit_percent": industry_limit_percent}
    oos = [row for row in trades if out_of_sample_start and row["entry_date"] >= out_of_sample_start]
    oos_returns = [row["net_return_percent"] for row in oos]
    portfolio = simulate_fixed_capital_trades(trades, **constraints)
    matched_benchmark = _same_exposure_index_benchmark(
        database, trades, commission_bps=commission_bps, sell_tax_bps=sell_tax_bps,
        slippage_bps=slippage_bps, constraints=constraints)
    oos_report = None
    if out_of_sample_start:
        oos_benchmark = _same_exposure_index_benchmark(
            database, oos, commission_bps=commission_bps, sell_tax_bps=sell_tax_bps,
            slippage_bps=slippage_bps, constraints=constraints)
        oos_report = {"start_date": out_of_sample_start, "trades": len(oos),
                      "win_rate_percent": round(sum(value > 0 for value in oos_returns) / len(oos_returns) * 100, 2) if oos_returns else None,
                      "average_net_return_percent": round(mean(oos_returns), 4) if oos_returns else None,
                      "portfolio_simulation": simulate_fixed_capital_trades(oos, **constraints),
                      "benchmark_status": oos_benchmark["status"]}
    audit_records = [{"symbol": row["symbol"], "decision_date": row["signal_date"],
                      "available_at": row["signal_date"], "execution_date": row["entry_date"]}
                     for row in trades]
    return {"mode": "technical_ema_adx_atr_backtest", "strategy": "ema20_ema100_adx_atr_v1", "trades": len(trades), "win_rate_percent": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None, "average_net_return_percent": round(mean(returns), 4) if returns else None, "portfolio_simulation": portfolio, "allocation_matched_benchmark": matched_benchmark, "out_of_sample": oos_report, "out_of_sample_allocation_matched_benchmark": oos_benchmark if out_of_sample_start else None, "parameters": {"fast_ema": fast_ema, "slow_ema": slow_ema, "trend_ema": trend_ema, "exit_ema": exit_ema, "adx_threshold": adx_threshold, "initial_stop_atr": initial_stop_atr, "trailing_stop_atr": trailing_stop_atr, "commission_bps_per_side": commission_bps, "sell_tax_bps": sell_tax_bps, "slippage_bps_per_side": slippage_bps, "minimum_daily_turnover": min_turnover, "start_date": start_date, "end_date": end_date, "out_of_sample_start": out_of_sample_start}, "outcomes": trades[-300:], "audit_records": audit_records, "formal_recommendation_allowed": False, "limitations": ["Predeclared research rule; it cannot alter recommendations or positions.", "Signals use stored daily OHLCV at close and execute at the next session open.", "The out-of-sample split is a reporting boundary; parameters remain fixed.", "The matching benchmark is a TAIEX close-to-close proxy, not an executable ETF benchmark.", "Daily stop handling is conservative; corporate actions, delistings and intraday order-book execution remain incomplete."]}


def bollinger_rsi_mean_reversion_backtest(
    database: Database, *, band_period: int = 20, rsi_period: int = 14,
    rsi_entry: float = 30, max_holding_days: int = 10, stop_atr_multiple: float = 2,
    commission_bps: float = 14.25, sell_tax_bps: float = 30, slippage_bps: float = 5,
    min_turnover: float = 10_000_000, max_total_exposure_percent: float = 80,
    single_stock_limit_percent: float = 10, industry_limit_percent: float = 25,
    start_date: str | None = None, end_date: str | None = None,
    out_of_sample_start: str | None = None,
) -> dict:
    """Fixed, long-only mean-reversion study; close signals execute next open."""
    with database.connect() as connection:
        instruments = {(row["symbol"], row["market"]): dict(row) for row in connection.execute(
            "SELECT symbol,market,name,industry FROM instruments")}
        prices = [dict(row) for row in connection.execute(
            "SELECT symbol,market,trade_date,open,high,low,close,volume FROM daily_prices ORDER BY symbol,market,trade_date")]
    series: dict[tuple[str, str], list[dict]] = {}
    for row in prices:
        series.setdefault((row["symbol"], row["market"]), []).append(row)
    trades = []
    for key, rows in series.items():
        last_index = max((index for index, row in enumerate(rows)
                          if not end_date or row["trade_date"] <= end_date), default=-1)
        warmup = max(band_period, rsi_period + 1, 15)
        if last_index <= warmup:
            continue
        closes = [float(row["close"]) for row in rows]
        middle, lower = _bollinger(closes, band_period)
        rsi, next_allowed = _rsi_series(closes, rsi_period), 0
        for index in range(warmup, last_index):
            if index < next_allowed or (start_date and rows[index]["trade_date"] < start_date):
                continue
            if None in (middle[index], lower[index], rsi[index]) or not (closes[index] < lower[index] and rsi[index] < rsi_entry):
                continue
            entry_index = index + 1
            if entry_index >= last_index or float(rows[entry_index]["open"]) * float(rows[entry_index].get("volume") or 0) < min_turnover:
                continue
            atr = _atr(rows, index)
            if not atr:
                continue
            entry = float(rows[entry_index]["open"])
            stop = entry - stop_atr_multiple * atr
            exit_index = min(entry_index + max_holding_days, last_index)
            exit_price, reason = float(rows[exit_index]["close"]), "end_of_test" if end_date and exit_index == last_index else "time_exit"
            for candidate in range(entry_index, exit_index + 1):
                if float(rows[candidate]["low"]) <= stop:
                    exit_index, exit_price, reason = candidate, min(float(rows[candidate]["open"]), stop), "atr_stop"
                    break
                if closes[candidate] >= middle[candidate]:
                    exit_index, exit_price, reason = candidate, float(rows[candidate]["close"]), "mean_reversion_exit"
                    break
            buy_cost = (commission_bps + slippage_bps) / 10_000
            sell_cost = (commission_bps + sell_tax_bps + slippage_bps) / 10_000
            instrument = instruments[key]
            trades.append({"symbol": key[0], "market": key[1], "name": instrument.get("name"),
                           "industry": instrument.get("industry") or "unknown", "signal_date": rows[index]["trade_date"],
                           "entry_date": rows[entry_index]["trade_date"], "exit_date": rows[exit_index]["trade_date"],
                           "exit_reason": reason, "rsi": round(rsi[index], 4),
                           "net_return_percent": round(((exit_price * (1 - sell_cost)) / (entry * (1 + buy_cost)) - 1) * 100, 4)})
            next_allowed = exit_index + 1
    constraints = {"max_total_exposure_percent": max_total_exposure_percent,
                   "single_stock_limit_percent": single_stock_limit_percent,
                   "industry_limit_percent": industry_limit_percent}
    returns = [row["net_return_percent"] for row in trades]
    oos = [row for row in trades if out_of_sample_start and row["entry_date"] >= out_of_sample_start]
    oos_returns = [row["net_return_percent"] for row in oos]
    benchmark = _same_exposure_index_benchmark(database, trades, commission_bps=commission_bps,
                                                sell_tax_bps=sell_tax_bps, slippage_bps=slippage_bps,
                                                constraints=constraints)
    oos_benchmark = _same_exposure_index_benchmark(database, oos, commission_bps=commission_bps,
                                                    sell_tax_bps=sell_tax_bps, slippage_bps=slippage_bps,
                                                    constraints=constraints) if out_of_sample_start else None
    return {"mode": "technical_bollinger_rsi_backtest", "strategy": "bollinger20_rsi14_mean_reversion_v1",
            "trades": len(trades), "win_rate_percent": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
            "average_net_return_percent": round(mean(returns), 4) if returns else None,
            "portfolio_simulation": simulate_fixed_capital_trades(trades, **constraints),
            "allocation_matched_benchmark": benchmark,
            "out_of_sample": {"start_date": out_of_sample_start, "trades": len(oos),
                                "win_rate_percent": round(sum(value > 0 for value in oos_returns) / len(oos_returns) * 100, 2) if oos_returns else None,
                                "average_net_return_percent": round(mean(oos_returns), 4) if oos_returns else None,
                                "portfolio_simulation": simulate_fixed_capital_trades(oos, **constraints),
                                "benchmark_status": oos_benchmark["status"]} if out_of_sample_start else None,
            "out_of_sample_allocation_matched_benchmark": oos_benchmark,
            "parameters": {"band_period": band_period, "rsi_period": rsi_period, "rsi_entry": rsi_entry,
                           "max_holding_days": max_holding_days, "stop_atr_multiple": stop_atr_multiple,
                           "commission_bps_per_side": commission_bps, "sell_tax_bps": sell_tax_bps,
                           "slippage_bps_per_side": slippage_bps, "minimum_daily_turnover": min_turnover,
                           "start_date": start_date, "end_date": end_date, "out_of_sample_start": out_of_sample_start},
            "outcomes": trades[-300:], "audit_records": [{"symbol": row["symbol"], "decision_date": row["signal_date"], "available_at": row["signal_date"], "execution_date": row["entry_date"]} for row in trades],
            "formal_recommendation_allowed": False,
            "limitations": ["Research-only fixed rule; it cannot alter recommendations or positions.",
                            "Signal uses the close and enters at next-session open; daily bars use a conservative stop convention.",
                            "TAIEX comparison is a close-to-close same-exposure proxy, not an executable ETF benchmark.",
                            "Corporate actions, delistings and intraday order-book execution remain incomplete."]}


def _atr(rows: list[dict], end: int, period: int = 14) -> float | None:
    if end < period:
        return None
    ranges = []
    for index in range(end - period + 1, end + 1):
        row, previous = rows[index], rows[index - 1]
        high, low, close = float(row["high"]), float(row["low"]), float(previous["close"])
        ranges.append(max(high - low, abs(high - close), abs(low - close)))
    return mean(ranges)


def _bucket(value: float, boundaries: tuple[float, ...], labels: tuple[str, ...]) -> str:
    for boundary, label in zip(boundaries, labels):
        if value < boundary:
            return label
    return labels[-1]


def _trade_breakdown(trades: list[dict], field: str) -> list[dict]:
    groups: dict[str, list[float]] = {}
    for trade in trades:
        groups.setdefault(str(trade[field]), []).append(trade["net_return_percent"])
    return [{"group": group, "trades": len(values),
             "win_rate_percent": round(sum(value > 0 for value in values) / len(values) * 100, 2),
             "average_net_return_percent": round(mean(values), 4)}
            for group, values in sorted(groups.items())]


def breakout_atr_signal_candidates(database: Database, signal_date: str, *, lookback: int = 20,
                                  volume_multiple: float = 1.5, min_breakout_percent: float = 3) -> list[dict]:
    """Return only signals observable at a specified close; no future execution data."""
    with database.connect() as connection:
        instruments = {(row["symbol"], row["market"]): dict(row) for row in connection.execute(
            "SELECT symbol,market,name,industry FROM instruments")}
        prices = [dict(row) for row in connection.execute(
            "SELECT symbol,market,trade_date,open,high,low,close,volume FROM daily_prices WHERE trade_date<=? ORDER BY symbol,market,trade_date",
            (signal_date,))]
    by_symbol: dict[tuple[str, str], list[dict]] = {}
    for row in prices:
        by_symbol.setdefault((row["symbol"], row["market"]), []).append(row)
    candidates = []
    warmup = max(60, lookback + 1, 15)
    for key, rows in by_symbol.items():
        index = len(rows) - 1
        if index < warmup or rows[index]["trade_date"] != signal_date:
            continue
        closes = [float(item["close"]) for item in rows]
        prior_high = max(closes[index - lookback:index])
        ma20 = mean(closes[index - 19:index + 1])
        ma60 = mean(closes[index - 59:index + 1])
        average_volume = mean(float(item.get("volume") or 0) for item in rows[index - lookback:index])
        breakout_strength = (closes[index] / prior_high - 1) * 100
        if not (breakout_strength >= min_breakout_percent and closes[index] > prior_high and closes[index] >= ma20 >= ma60
                and float(rows[index].get("volume") or 0) >= average_volume * volume_multiple):
            continue
        atr = _atr(rows, index)
        if not atr:
            continue
        instrument = instruments[key]
        candidates.append({"symbol": key[0], "market": key[1], "name": instrument.get("name"),
                           "industry": instrument.get("industry") or "unknown", "signal_date": signal_date,
                           "atr": round(atr, 6), "breakout_strength_percent": round(breakout_strength, 4),
                           "relative_volume": round(float(rows[index].get("volume") or 0) / average_volume, 4)})
    return sorted(candidates, key=lambda row: (-row["breakout_strength_percent"], -row["relative_volume"], row["symbol"]))


def breakout_atr_backtest(
    database: Database, lookback: int = 20, volume_multiple: float = 1.5,
    min_breakout_percent: float = 3,
    max_holding_days: int = 20, stop_atr_multiple: float = 2,
    reward_risk: float = 2, commission_bps: float = 14.25,
    sell_tax_bps: float = 30, slippage_bps: float = 5,
    min_turnover: float = 10_000_000, start_date: str | None = None,
    end_date: str | None = None,
    out_of_sample_start: str | None = None,
    max_total_exposure_percent: float = 80, single_stock_limit_percent: float = 10,
    industry_limit_percent: float = 25,
) -> dict:
    """Point-in-time daily breakout simulation, one independent trade per symbol.

    Signal data ends at day *t*; execution is next session's open. It is not a
    portfolio simulation and intentionally keeps parameters explicit for audit.
    """
    with database.connect() as connection:
        symbols = [dict(row) for row in connection.execute(
            "SELECT symbol,market,name,industry FROM instruments ORDER BY market,symbol"
        )]
        all_prices = [dict(row) for row in connection.execute(
            """SELECT symbol,market,trade_date,open,high,low,close,volume
               FROM daily_prices ORDER BY symbol,market,trade_date"""
        )]
    by_symbol: dict[tuple[str, str], list[dict]] = {}
    for row in all_prices:
        by_symbol.setdefault((row["symbol"], row["market"]), []).append(row)
    instruments = {(row["symbol"], row["market"]): row for row in symbols}
    trades: list[dict] = []
    signals = liquidity_excluded = 0
    warmup = max(60, lookback + 1, 15)
    for key, rows in by_symbol.items():
        last_index = max((index for index, row in enumerate(rows)
                          if not end_date or row["trade_date"] <= end_date), default=-1)
        if last_index <= warmup:
            continue
        closes = [float(item["close"]) for item in rows]
        next_allowed = 0
        for index in range(warmup, last_index):
            if index < next_allowed:
                continue
            signal, entry = rows[index], rows[index + 1]
            if index + 1 >= last_index:
                continue
            if (start_date and signal["trade_date"] < start_date) or (end_date and signal["trade_date"] > end_date):
                continue
            prior_high = max(closes[index - lookback:index])
            ma20 = mean(closes[index - 19:index + 1])
            ma60 = mean(closes[index - 59:index + 1])
            average_volume = mean(float(item.get("volume") or 0) for item in rows[index - lookback:index])
            breakout_strength = (float(signal["close"]) / prior_high - 1) * 100
            if not (breakout_strength >= min_breakout_percent and float(signal["close"]) > prior_high
                    and float(signal["close"]) >= ma20 >= ma60
                    and float(signal.get("volume") or 0) >= average_volume * volume_multiple):
                continue
            signals += 1
            if float(entry["open"]) * float(entry.get("volume") or 0) < min_turnover:
                liquidity_excluded += 1
                continue
            atr = _atr(rows, index)
            if not atr:
                continue
            entry_price = float(entry["open"])
            stop = entry_price - stop_atr_multiple * atr
            target = entry_price + reward_risk * (entry_price - stop)
            exit_index = min(index + max_holding_days, last_index)
            exit_row, exit_price, reason = rows[exit_index], None, "end_of_test" if end_date and exit_index == last_index else "time_exit"
            for candidate_index in range(index + 1, min(index + max_holding_days + 1, last_index + 1)):
                candidate = rows[candidate_index]
                # Conservative daily-bar convention: if both could occur, stop wins.
                if float(candidate["low"]) <= stop:
                    exit_row, exit_index, exit_price, reason = candidate, candidate_index, stop, "atr_stop"
                    break
                if float(candidate["high"]) >= target:
                    exit_row, exit_index, exit_price, reason = candidate, candidate_index, target, "two_r_target"
                    break
            if exit_price is None:
                exit_price = float(exit_row["close"])
            buy_cost = (commission_bps + slippage_bps) / 10_000
            sell_cost = (commission_bps + sell_tax_bps + slippage_bps) / 10_000
            net_return = ((exit_price * (1 - sell_cost)) / (entry_price * (1 + buy_cost)) - 1) * 100
            relative_volume = float(signal.get("volume") or 0) / average_volume if average_volume else 0
            instrument = instruments.get(key, {})
            trades.append({"symbol": key[0], "market": key[1], "name": instrument.get("name"),
                           "industry": instrument.get("industry") or "unknown",
                           "signal_date": signal["trade_date"], "entry_date": entry["trade_date"],
                           "exit_date": exit_row["trade_date"], "entry_price": round(entry_price, 4),
                           "exit_price": round(exit_price, 4), "atr": round(atr, 4),
                           "exit_reason": reason, "holding_days": exit_index - (index + 1) + 1,
                           "breakout_strength_percent": round(breakout_strength, 4),
                           "relative_volume": round(relative_volume, 4),
                           "breakout_bucket": _bucket(breakout_strength, (1, 3), ("<1%", "1%-3%", ">=3%")),
                           "volume_bucket": _bucket(relative_volume, (1.5, 2), ("1.2x-1.5x", "1.5x-2x", ">=2x")),
                           "signal_year": signal["trade_date"][:4],
                           "net_return_percent": round(net_return, 4)})
            next_allowed = exit_index + 1
    returns = [trade["net_return_percent"] for trade in trades]
    portfolio = simulate_fixed_capital_trades(
        trades, max_total_exposure_percent=max_total_exposure_percent,
        single_stock_limit_percent=single_stock_limit_percent,
        industry_limit_percent=industry_limit_percent,
    )
    constraints = {"max_total_exposure_percent": max_total_exposure_percent,
                   "single_stock_limit_percent": single_stock_limit_percent,
                   "industry_limit_percent": industry_limit_percent}
    matched_benchmark = _same_exposure_index_benchmark(
        database, trades, commission_bps=commission_bps, sell_tax_bps=sell_tax_bps,
        slippage_bps=slippage_bps, constraints=constraints)
    oos = [trade for trade in trades if out_of_sample_start and trade["entry_date"] >= out_of_sample_start]
    oos_returns = [trade["net_return_percent"] for trade in oos]
    oos_report = None
    if out_of_sample_start:
        oos_benchmark = _same_exposure_index_benchmark(
            database, oos, commission_bps=commission_bps, sell_tax_bps=sell_tax_bps,
            slippage_bps=slippage_bps, constraints=constraints)
        oos_report = {"start_date": out_of_sample_start, "trades": len(oos),
                      "win_rate_percent": round(sum(value > 0 for value in oos_returns) / len(oos_returns) * 100, 2) if oos_returns else None,
                      "average_net_return_percent": round(mean(oos_returns), 4) if oos_returns else None,
                      "portfolio_simulation": simulate_fixed_capital_trades(oos, **constraints),
                      "benchmark_status": oos_benchmark["status"]}
    audit_records = [{"symbol": trade["symbol"], "decision_date": trade["signal_date"],
                      "available_at": trade["signal_date"], "execution_date": trade["entry_date"]}
                     for trade in trades]
    return {"mode": "technical_breakout_backtest", "strategy": "20d_breakout_volume_atr",
            "signals": signals, "liquidity_excluded": liquidity_excluded, "trades": len(trades),
            "win_rate_percent": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
            "average_net_return_percent": round(mean(returns), 4) if returns else None,
            "portfolio_simulation": portfolio,
            "allocation_matched_benchmark": matched_benchmark,
            "out_of_sample": oos_report,
            "out_of_sample_allocation_matched_benchmark": oos_benchmark if out_of_sample_start else None,
            "diagnostics": {
                "by_exit_reason": _trade_breakdown(trades, "exit_reason"),
                "by_breakout_strength": _trade_breakdown(trades, "breakout_bucket"),
                "by_relative_volume": _trade_breakdown(trades, "volume_bucket"),
                "by_signal_year": _trade_breakdown(trades, "signal_year"),
            },
            "parameters": {"lookback_days": lookback, "volume_multiple": volume_multiple,
                           "min_breakout_percent": min_breakout_percent,
                           "max_holding_days": max_holding_days, "stop_atr_multiple": stop_atr_multiple,
                           "reward_risk": reward_risk, "minimum_daily_turnover": min_turnover,
                           "commission_bps_per_side": commission_bps, "sell_tax_bps": sell_tax_bps,
                           "slippage_bps_per_side": slippage_bps, "start_date": start_date,
                           "end_date": end_date, "out_of_sample_start": out_of_sample_start},
            "outcomes": trades[-300:],
            "audit_records": audit_records,
            "formal_recommendation_allowed": False,
            "limitations": ["The shared-capital simulation books open trades at cost until exit, so it does not claim an intraday marked-to-market drawdown.",
                            "The default quality gates (>=3% breakout and >=1.5x relative volume) were selected using 2023-2024 results and checked against 2025-2026; they remain research parameters, not a guarantee.",
                            "Signals use current instrument membership, so survivorship and delisting bias remain.",
                            "Daily OHLC bars use a conservative stop-first assumption; gaps and order-book execution are not modelled.",
                            "Cash/stock dividends, capital changes and suspensions are not fully modelled.",
                            "Historical results are research only and do not guarantee future returns."]}
