from __future__ import annotations

from collections import defaultdict


def construct_portfolio(
    candidates: list[dict], *, max_total_exposure_percent: float,
    single_stock_limit_percent: float = 10, industry_limit_percent: float = 25,
) -> dict:
    """Apply deterministic long-only exposure limits to ranked candidates.

    The interface deliberately accepts plain candidate records so live decisions,
    historical backtests and research experiments all receive identical limits.
    """
    exposure_limit = max(0.0, min(100.0, max_total_exposure_percent))
    single_limit = max(0.0, min(single_stock_limit_percent, exposure_limit))
    industry_limit = max(0.0, min(industry_limit_percent, exposure_limit))
    industry_used: dict[str, float] = defaultdict(float)
    allocations, rejected = [], []
    remaining = exposure_limit
    requested = exposure_limit / len(candidates) if candidates else 0.0
    for candidate in candidates:
        symbol = candidate.get("symbol")
        industry = candidate.get("industry") or "unknown"
        if not symbol or remaining <= 0:
            rejected.append({"symbol": symbol, "reason": "total_exposure_limit"})
            continue
        available_industry = max(0.0, industry_limit - industry_used[industry])
        allocation = min(requested, single_limit, available_industry, remaining)
        if allocation <= 0:
            rejected.append({"symbol": symbol, "reason": "industry_limit"})
            continue
        industry_used[industry] += allocation
        remaining -= allocation
        allocations.append({**candidate, "industry": industry,
                            "target_weight_percent": round(allocation, 4)})
    invested = round(sum(row["target_weight_percent"] for row in allocations), 4)
    return {"allocations": allocations, "rejected": rejected,
            "invested_percent": invested, "cash_percent": round(100 - invested, 4),
            "constraints": {"max_total_exposure_percent": exposure_limit,
                            "single_stock_limit_percent": single_limit,
                            "industry_limit_percent": industry_limit}}


def portfolio_period_return(
    allocations: list[dict], *, commission_bps: float,
    sell_tax_bps: float, slippage_bps: float,
) -> dict:
    """Calculate one rebalance-period return using realised candidate returns."""
    gross = sum(float(row["target_weight_percent"]) / 100 * float(row["return_percent"])
                for row in allocations)
    exposure = sum(float(row["target_weight_percent"]) for row in allocations) / 100
    costs = exposure * (commission_bps + sell_tax_bps / 2 + slippage_bps * 2) / 10_000 * 100
    return {"gross_return_percent": round(gross, 4), "cost_percent": round(costs, 4),
            "net_return_percent": round(gross - costs, 4),
            "invested_percent": round(exposure * 100, 4)}


def simulate_fixed_capital_trades(
    trades: list[dict], *, initial_capital: float = 100.0,
    max_total_exposure_percent: float = 80.0,
    single_stock_limit_percent: float = 10.0,
    industry_limit_percent: float = 25.0,
) -> dict:
    """Simulate overlapping trades against one shared, compounding cash account.

    ``net_return_percent`` must already include the trade-level execution costs.
    Entries on the same date are ranked deterministically (rank, then symbol),
    so a historical result cannot depend on database iteration order.  Open
    positions are held at cost until their recorded exit: this deliberately
    avoids inventing intraday marks from a trade-only input.
    """
    capital = max(float(initial_capital), 0.01)
    cash = capital
    positions: list[dict] = []
    rejected: list[dict] = []
    equity_curve: list[dict] = []

    entries: dict[str, list[dict]] = defaultdict(list)
    exits: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        if not trade.get("entry_date") or not trade.get("exit_date"):
            rejected.append({"symbol": trade.get("symbol"), "reason": "missing_trade_dates"})
            continue
        entries[str(trade["entry_date"])].append(trade)
        exits[str(trade["exit_date"])].append(trade)

    for trade_date in sorted(set(entries) | set(exits)):
        # Release capital first.  A same-day exit can therefore fund a next
        # session entry, but positions never use future exit proceeds.
        for trade in exits.get(trade_date, []):
            for position in list(positions):
                if position["trade"] is trade:
                    proceeds = position["cost"] * (1 + float(trade["net_return_percent"]) / 100)
                    cash += proceeds
                    positions.remove(position)
                    break

        book_value = sum(position["cost"] for position in positions)
        equity_before_entries = cash + book_value
        exposure_capital = equity_before_entries * max(0, min(max_total_exposure_percent, 100)) / 100
        available_total = max(0.0, exposure_capital - book_value)
        industry_used: dict[str, float] = defaultdict(float)
        for position in positions:
            industry_used[position["industry"]] += position["cost"]

        ordered = sorted(entries.get(trade_date, []), key=lambda row: (row.get("rank", 999999), row.get("symbol", "")))
        remaining_candidates = len(ordered)
        for trade in ordered:
            industry = trade.get("industry") or "unknown"
            single_capital = equity_before_entries * max(0, single_stock_limit_percent) / 100
            industry_capital = equity_before_entries * max(0, industry_limit_percent) / 100
            equal_share = available_total / remaining_candidates if remaining_candidates else 0
            amount = min(cash, available_total, single_capital,
                         max(0.0, industry_capital - industry_used[industry]), equal_share)
            remaining_candidates -= 1
            if amount <= 0.000001:
                rejected.append({"symbol": trade.get("symbol"), "entry_date": trade_date,
                                 "reason": "cash_or_risk_limit"})
                continue
            cash -= amount
            available_total -= amount
            industry_used[industry] += amount
            positions.append({"trade": trade, "cost": amount, "industry": industry})

        # A daily OHLC strategy can enter at the open and hit a stop or target
        # later that same session.  These exits cannot fund any other entries
        # above (the allocation pass is already complete), but they must be
        # settled before the end-of-day equity record.
        for trade in exits.get(trade_date, []):
            for position in list(positions):
                if position["trade"] is trade:
                    proceeds = position["cost"] * (1 + float(trade["net_return_percent"]) / 100)
                    cash += proceeds
                    positions.remove(position)
                    break

        book_value = sum(position["cost"] for position in positions)
        equity = cash + book_value
        equity_curve.append({"date": trade_date, "equity": round(equity, 6),
                             "cash": round(cash, 6), "invested": round(book_value, 6),
                             "open_positions": len(positions)})

    final_equity = cash + sum(position["cost"] for position in positions)
    return {"initial_capital": round(capital, 6), "ending_capital": round(final_equity, 6),
            "net_return_percent": round((final_equity / capital - 1) * 100, 4),
            "equity_curve": equity_curve, "rejected_trades": rejected,
            "constraints": {"max_total_exposure_percent": max_total_exposure_percent,
                            "single_stock_limit_percent": single_stock_limit_percent,
                            "industry_limit_percent": industry_limit_percent},
            "unclosed_positions": len(positions)}
