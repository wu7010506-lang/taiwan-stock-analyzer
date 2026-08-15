from __future__ import annotations

import json
from datetime import date

from app.backtest import historical_backtest
from app.database import Database
from app.research_lab import FACTOR_ABLATION_CONFIGURATIONS
from app.technical_strategy_backtest import breakout_atr_signal_candidates
from app.short_term_decision import short_term_fundamental_candidates


INITIAL_CAPITAL = 100.0
BUY_COST_RATE = (14.25 + 5) / 10_000
SELL_COST_RATE = (14.25 + 30 + 5) / 10_000
TARGET_EXPOSURE_PERCENT = 80.0
PROMOTION_POLICY = {
    "minimum_out_of_sample_months": 12,
    "required_positive_excess_return": True,
    "automatic_promotion": False,
    "rule": "A human must review a locked future sample; paper results never change formal recommendations automatically.",
}


def _candidate_definitions() -> list[dict]:
    selected = [row for row in FACTOR_ABLATION_CONFIGURATIONS if row["name"] in {"baseline", "cashflow_tilt"}]
    return ([{"strategy_key": f"paper_{row['name']}", "strategy_version": f"factor-{row['name']}-v1",
              "kind": "factor", "weights": row["weights"]} for row in selected] +
            [{"strategy_key": "paper_technical_breakout_atr", "strategy_version": "breakout-atr-paper-v1",
              "kind": "technical_breakout", "max_positions": 8, "target_weight_percent": 10,
              "max_holding_sessions": 20, "stop_atr_multiple": 2, "reward_risk": 2},
             {"strategy_key": "paper_short_term_breakout_10d", "strategy_version": "short-term-breakout-10d-paper-v1",
              "kind": "technical_breakout_short_term", "max_positions": 8, "target_weight_percent": 5,
              "max_holding_sessions": 10, "stop_atr_multiple": 2, "reward_risk": 2,
              "fundamental_gate": "short_term_safety_gate_v1"}])


def ensure_paper_candidates(database: Database) -> list[dict]:
    for row in _candidate_definitions():
        parameters = {key: value for key, value in row.items() if key not in {"strategy_key", "strategy_version", "weights"}}
        database.upsert_paper_strategy_candidate(
            row["strategy_key"], row["strategy_version"], "locked_research_candidate",
            json.dumps({**parameters, "weights": row.get("weights"), "initial_capital": INITIAL_CAPITAL,
                        "execution": "next_available_session_open", "valuation": "daily_close"}, sort_keys=True),
            json.dumps(PROMOTION_POLICY, sort_keys=True),
        )
    return database.list_paper_strategy_candidates()


def _data_version(database: Database, as_of_date: str) -> dict:
    quality = database.list_data_quality_snapshots(1)
    sync = database.get_latest_daily_sync_run()
    return {"decision_date": as_of_date, "daily_sync_run_id": (sync or {}).get("id"),
            "quality_snapshot_id": quality[0]["id"] if quality else None,
            "price_convention": "next_available_session_open / daily_close_mark"}


def _latest_market_session(database: Database, as_of_date: str) -> str | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT MAX(trade_date) AS trade_date FROM daily_prices WHERE trade_date<=?", (as_of_date,)
        ).fetchone()
    return row["trade_date"] if row and row["trade_date"] else None


def _latest_price_on_or_before(database: Database, symbol: str, market: str, as_of_date: str) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM daily_prices WHERE symbol=? AND market=? AND trade_date<=?
               ORDER BY trade_date DESC LIMIT 1""", (symbol, market, as_of_date)).fetchone()
    return dict(row) if row else None


def _first_price_after(database: Database, symbol: str, market: str, signal_date: str) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM daily_prices WHERE symbol=? AND market=? AND trade_date>?
               ORDER BY trade_date LIMIT 1""", (symbol, market, signal_date)).fetchone()
    return dict(row) if row else None


def _queue_rebalance_orders(database: Database, definition: dict, signal_date: str, version: dict) -> int:
    report = historical_backtest(database, horizon=20, top_n=10, min_score=65,
                                 start_date=signal_date, end_date=signal_date,
                                 min_turnover=10_000_000, research_weights=definition["weights"])
    snapshots = report.get("selection_snapshots") or []
    selected = snapshots[0]["selected"] if snapshots else []
    queued = 0
    # Fully reset to the monthly target basket.  This deliberately mirrors the
    # walk-forward model's equal-weight monthly rebalance rather than silently
    # letting winners drift above their target weights.
    for position in database.list_paper_positions(definition["strategy_key"]):
        database.add_paper_order({"strategy_key": definition["strategy_key"], "signal_date": signal_date,
                                  "symbol": position["symbol"], "market": position["market"], "side": "sell",
                                  "target_weight_percent": 0, "data_version_json": json.dumps(version, sort_keys=True)})
        queued += 1
    if not selected:
        return queued
    target = TARGET_EXPOSURE_PERCENT / len(selected)
    for row in selected:
        database.add_paper_order({"strategy_key": definition["strategy_key"], "signal_date": signal_date,
                                  "symbol": row["symbol"], "market": row["market"], "side": "buy",
                                  "target_weight_percent": target,
                                  "data_version_json": json.dumps(version, sort_keys=True)})
        queued += 1
    return queued


def _session_count(database: Database, symbol: str, market: str, opened_at: str, as_of: str) -> int:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM daily_prices WHERE symbol=? AND market=? AND trade_date>? AND trade_date<=?",
            (symbol, market, opened_at, as_of),
        ).fetchone()
    return int(row["count"])


def _queue_technical_breakout_orders(database: Database, definition: dict, signal_date: str,
                                     as_of: str, version: dict) -> int:
    """Queue only locked breakout signals and delayed, auditable paper exits."""
    key, pending = definition["strategy_key"], database.list_paper_orders(definition["strategy_key"], "pending")
    pending_keys = {(row["symbol"], row["market"], row["side"]) for row in pending}
    queued = 0
    for position in database.list_paper_positions(key):
        if (position["symbol"], position["market"], "sell") in pending_keys:
            continue
        buy = database.get_latest_paper_order(key, position["symbol"], position["market"], "buy")
        meta = json.loads(buy["data_version_json"]) if buy else {}
        atr = float(meta.get("atr") or 0)
        latest = _latest_price_on_or_before(database, position["symbol"], position["market"], as_of)
        reason = None
        if latest and atr and float(latest["low"]) <= float(position["average_cost"]) - definition["stop_atr_multiple"] * atr:
            reason = "atr_stop_observed_after_close"
        elif latest and atr and float(latest["high"]) >= float(position["average_cost"]) + definition["reward_risk"] * definition["stop_atr_multiple"] * atr:
            reason = "target_observed_after_close"
        elif _session_count(database, position["symbol"], position["market"], position["opened_at"], as_of) >= definition["max_holding_sessions"]:
            reason = "max_holding_sessions"
        if reason:
            database.add_paper_order({"strategy_key": key, "signal_date": signal_date,
                                      "symbol": position["symbol"], "market": position["market"], "side": "sell",
                                      "target_weight_percent": 0,
                                      "data_version_json": json.dumps({**version, "exit_trigger": reason}, sort_keys=True)})
            queued += 1
    positions = database.list_paper_positions(key)
    pending_buys = [row for row in pending if row["side"] == "buy"]
    capacity = max(0, definition["max_positions"] - len(positions) - len(pending_buys))
    existing = {(row["symbol"], row["market"]) for row in positions + pending_buys}
    industry_count: dict[str, int] = {}
    for row in positions:
        # Unknown is intentionally capped too; this prevents concentration from missing metadata.
        industry_count["unknown"] = industry_count.get("unknown", 0) + 1
    eligible = None
    if definition.get("fundamental_gate") == "short_term_safety_gate_v1":
        eligible = {(row["symbol"], row["market"]) for row in short_term_fundamental_candidates(
            database, date.fromisoformat(signal_date)
        )}
    for candidate in breakout_atr_signal_candidates(database, signal_date):
        if eligible is not None and (candidate["symbol"], candidate["market"]) not in eligible:
            continue
        if capacity <= 0 or (candidate["symbol"], candidate["market"]) in existing:
            continue
        industry = candidate["industry"] or "unknown"
        if industry_count.get(industry, 0) >= 2:
            continue
        database.add_paper_order({"strategy_key": key, "signal_date": signal_date,
                                  "symbol": candidate["symbol"], "market": candidate["market"], "side": "buy",
                                  "target_weight_percent": definition["target_weight_percent"],
                                  "data_version_json": json.dumps({**version, **candidate}, sort_keys=True)})
        existing.add((candidate["symbol"], candidate["market"])); industry_count[industry] = industry_count.get(industry, 0) + 1
        capacity -= 1; queued += 1
    return queued


def _latest_index_on_or_before(database: Database, as_of_date: str) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT trade_date,close FROM market_index_snapshots WHERE trade_date<=?
               ORDER BY trade_date DESC LIMIT 1""", (as_of_date,)).fetchone()
    return dict(row) if row else None


def _benchmark_nav(previous: dict | None, index: dict | None) -> float | None:
    if not index:
        return None
    if not previous or previous.get("benchmark_close") is None:
        return INITIAL_CAPITAL * (1 - TARGET_EXPOSURE_PERCENT / 100 * BUY_COST_RATE)
    old_close = float(previous["benchmark_close"])
    if old_close <= 0:
        return None
    return float(previous["benchmark_nav"]) * (1 + TARGET_EXPOSURE_PERCENT / 100 *
                                                  (float(index["close"]) / old_close - 1))


def _risk_metrics(valuations: list[dict]) -> dict:
    if not valuations:
        return {"return_percent": None, "benchmark_return_percent": None,
                "excess_return_percent": None, "max_drawdown_percent": None}
    latest_nav = float(valuations[-1]["nav"])
    peak, drawdown = INITIAL_CAPITAL, 0.0
    for row in valuations:
        nav = float(row["nav"])
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1)
    benchmark_values = [row for row in valuations if row.get("benchmark_nav") is not None]
    benchmark_return = None
    if benchmark_values:
        benchmark_return = (float(benchmark_values[-1]["benchmark_nav"]) / INITIAL_CAPITAL - 1) * 100
    strategy_return = (latest_nav / INITIAL_CAPITAL - 1) * 100
    return {"return_percent": round(strategy_return, 4),
            "benchmark_return_percent": round(benchmark_return, 4) if benchmark_return is not None else None,
            "excess_return_percent": round(strategy_return - benchmark_return, 4)
            if benchmark_return is not None else None,
            "max_drawdown_percent": round(drawdown * 100, 4)}


def run_paper_strategy_valuation(database: Database, as_of_date: date | None = None) -> dict:
    """Advance locked research candidates without modifying the production model."""
    as_of = (as_of_date or date.today()).isoformat()
    ensure_paper_candidates(database)
    version = _data_version(database, as_of)
    summaries = []
    for definition in _candidate_definitions():
        key = definition["strategy_key"]
        latest = database.get_latest_paper_valuation(key)
        cash = float(latest["cash"]) if latest else INITIAL_CAPITAL
        costs = 0.0
        base_nav = float(latest["nav"]) if latest else INITIAL_CAPITAL
        pending = sorted(database.list_paper_orders(key, "pending"), key=lambda row: row["side"] != "sell")
        for order in pending:
            execution = _first_price_after(database, order["symbol"], order["market"], order["signal_date"])
            if not execution or execution["trade_date"] > as_of:
                continue
            price = float(execution["open"])
            if price <= 0:
                database.execute_paper_order(order["id"], execution["trade_date"], price, 0, 0, "cancelled")
                continue
            if order["side"] == "sell":
                position = next((row for row in database.list_paper_positions(key)
                                 if row["symbol"] == order["symbol"] and row["market"] == order["market"]), None)
                if not position:
                    database.execute_paper_order(order["id"], execution["trade_date"], price, 0, 0, "cancelled")
                    continue
                shares = float(position["shares"])
                trade_cost = shares * price * SELL_COST_RATE
                cash += shares * price - trade_cost
                costs += trade_cost
                database.execute_paper_order(order["id"], execution["trade_date"], price, shares, trade_cost)
                database.remove_paper_position(key, order["symbol"], order["market"])
                continue
            amount = base_nav * float(order["target_weight_percent"]) / 100
            if order["side"] != "buy" or cash + 1e-9 < amount:
                database.execute_paper_order(order["id"], execution["trade_date"], price, 0, 0, "cancelled")
                continue
            trade_cost = amount * BUY_COST_RATE
            shares = (amount - trade_cost) / price
            cash -= amount
            costs += trade_cost
            database.execute_paper_order(order["id"], execution["trade_date"], price, shares, trade_cost)
            database.upsert_paper_position(key, order["symbol"], order["market"], shares, price,
                                           execution["trade_date"])
        holdings = 0.0
        valued_positions = 0
        for position in database.list_paper_positions(key):
            price = _latest_price_on_or_before(database, position["symbol"], position["market"], as_of)
            if price:
                holdings += float(position["shares"]) * float(price["close"])
                valued_positions += 1
        nav = cash + holdings
        index = _latest_index_on_or_before(database, as_of)
        benchmark_nav = _benchmark_nav(latest, index)
        database.save_paper_valuation({"strategy_key": key, "valuation_date": as_of, "cash": cash,
                                       "holdings_value": holdings, "nav": nav, "transaction_costs": costs,
                                       "benchmark_nav": benchmark_nav,
                                       "benchmark_close": index["close"] if index else None,
                                       "data_version_json": json.dumps(version, sort_keys=True)})
        signal_date = _latest_market_session(database, as_of)
        completed_orders = database.list_paper_orders(key)
        last_signal = max((row["signal_date"] for row in completed_orders), default=None)
        if definition["kind"] in {"technical_breakout", "technical_breakout_short_term"}:
            queued = _queue_technical_breakout_orders(database, definition, signal_date, as_of, version) if signal_date else 0
        else:
            queued = (_queue_rebalance_orders(database, definition, signal_date, version)
                      if signal_date and not database.list_paper_orders(key, "pending")
                      and (not last_signal or last_signal[:7] != signal_date[:7]) else 0)
        summaries.append({"strategy_key": key, "valuation_date": as_of, "nav": round(nav, 6),
                          "return_percent": round((nav / INITIAL_CAPITAL - 1) * 100, 4),
                          "cash": round(cash, 6), "holdings_value": round(holdings, 6),
                          "benchmark_nav": round(benchmark_nav, 6) if benchmark_nav is not None else None,
                          "valued_positions": valued_positions, "queued_orders": queued,
                          "pending_orders": len(database.list_paper_orders(key, "pending"))})
    return {"as_of_date": as_of, "mode": "locked_paper_strategy_tracking",
            "formal_recommendation_allowed": False, "summaries": summaries,
            "limitations": ["Orders are created after the signal close and execute at the next available session open.",
                            "The initial paper portfolios have no realised return until a later session exists.",
                            "Technical breakout exits are observed from the completed daily bar and queued for the next open; they are deliberately more conservative than same-day backtest fills.",
                            "Paper tracking is research evidence, not an investment recommendation or a guarantee."]}


def paper_strategy_summary(database: Database) -> dict:
    candidates = []
    for candidate in ensure_paper_candidates(database):
        key = candidate["strategy_key"]
        valuations = database.list_paper_valuations(key)
        latest = valuations[-1] if valuations else None
        policy = json.loads(candidate["promotion_policy_json"])
        forward_months = len({row["valuation_date"][:7] for row in valuations})
        metrics = _risk_metrics(valuations)
        if forward_months < int(policy["minimum_out_of_sample_months"]):
            evidence_status = "insufficient_forward_sample"
        elif metrics["excess_return_percent"] is None:
            evidence_status = "insufficient_benchmark"
        elif metrics["excess_return_percent"] <= 0:
            evidence_status = "rejected_underperforming"
        else:
            evidence_status = "human_review_required"
        candidates.append({"strategy_key": key, "strategy_version": candidate["strategy_version"],
                           "status": candidate["status"], "locked_at": candidate["locked_at"],
                           "promotion_policy": policy, "forward_months": forward_months,
                           "evidence_status": evidence_status, "metrics": metrics,
                           "valuations": valuations[-60:], "latest": latest,
                           "pending_orders": len(database.list_paper_orders(key, "pending")),
                           "positions": database.list_paper_positions(key),
                           "data_version": json.loads(latest["data_version_json"]) if latest else None,
                           "total_transaction_costs": round(sum(float(row["transaction_costs"]) for row in valuations), 6)})
    return {"mode": "paper_strategy_summary", "formal_recommendation_allowed": False,
            "candidates": candidates,
            "limitations": ["Promotion requires at least 12 locked future monthly observations and human review.",
                            "No candidate can alter formal recommendation weights automatically."]}
