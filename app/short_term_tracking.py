from __future__ import annotations

import json
from datetime import date
from statistics import mean, median

from app.database import Database
from app.short_term_decision import (
    STRATEGY_VERSION,
    _iso_date,
    build_short_term_decisions,
    short_term_fundamental_candidates,
)
from app.short_term_fundamentals import load_short_term_fundamental_assessment

HORIZONS = (3, 5, 10)
ASSUMED_ROUND_TRIP_COST_PERCENT = 0.785
MIN_EXACT_DATE_COVERAGE_PERCENT = 95.0
REQUIRED_MARKETS = ("TWSE", "TPEx")
MIN_FORWARD_MATURED_SIGNALS = 30
MIN_FORWARD_SIGNAL_DATES = 10


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def ranking_publication_gate(
    database: Database,
    result: dict,
    context: dict,
    *,
    minimum_coverage_percent: float = MIN_EXACT_DATE_COVERAGE_PERCENT,
) -> dict:
    """Require the index and both exchanges to be complete for the same session."""
    target_date = _iso_date(context.get("as_of")) or _iso_date(result.get("market_data_as_of"))
    signal_date = _iso_date(result.get("signal_date"))
    markets = {}
    eligible_counts = result.get("eligible_market_date_coverage") or {}
    if eligible_counts:
        counts = {
            market: {
                "recent_symbols": row.get("recent_symbols"),
                "exact_symbols": row.get("exact_date_symbols"),
            }
            for market, row in eligible_counts.items()
        }
        coverage_universe = "通過基本面安全門檻、可能參與排行榜的股票"
    else:
        with database.connect() as connection:
            rows = connection.execute(
                """WITH latest AS (
                       SELECT symbol, market, MAX(trade_date) AS latest_date
                       FROM daily_prices
                       WHERE market IN ('TWSE','TPEx')
                         AND date(trade_date)<=date(?)
                         AND date(trade_date)>=date(?, '-7 days')
                       GROUP BY symbol, market
                   )
                   SELECT market, COUNT(*) AS recent_symbols,
                          SUM(CASE WHEN latest_date=? THEN 1 ELSE 0 END) AS exact_symbols
                   FROM latest GROUP BY market""",
                (target_date, target_date, target_date),
            ) if target_date else []
            counts = {row["market"]: dict(row) for row in rows}
        coverage_universe = "最近七日有行情的證券（相容舊結果）"
    blocking_reasons = []
    for market in REQUIRED_MARKETS:
        counts_for_market = counts.get(market) or {}
        recent = int(counts_for_market.get("recent_symbols") or 0)
        exact = int(counts_for_market.get("exact_symbols") or 0)
        coverage = round(exact / recent * 100, 2) if recent else 0.0
        ready = recent > 0 and coverage >= minimum_coverage_percent
        markets[market] = {
            "recent_symbols": recent,
            "exact_date_symbols": exact,
            "exact_date_coverage_percent": coverage,
            "minimum_percent": minimum_coverage_percent,
            "ready": ready,
            "universe": coverage_universe,
        }
        if not ready:
            blocking_reasons.append(
                f"{market} 同日行情覆蓋 {coverage:.2f}%（最低 {minimum_coverage_percent:.0f}%）"
            )
    if not target_date:
        blocking_reasons.insert(0, "大盤資料日期無法辨識")
    elif signal_date != target_date:
        blocking_reasons.insert(0, "股票與大盤資料日期不一致")
    return {
        "ready": not blocking_reasons,
        "target_date": target_date,
        "signal_date": signal_date,
        "markets": markets,
        "blocking_reasons": blocking_reasons,
        "policy": "大盤、TWSE 與 TPEx 必須是同一交易日；兩市場同日行情覆蓋率各至少 95%。",
    }


def _ranking_changes(previous: dict | None, current: dict, limit: int) -> dict:
    old = (previous or {}).get("attention_rankings") or []
    new = (current.get("attention_rankings") or [])[:limit]
    old_map = {(str(row.get("symbol")), str(row.get("market"))): row for row in old[:limit]}
    new_map = {(str(row.get("symbol")), str(row.get("market"))): row for row in new}
    entered = [{
        "symbol": row.get("symbol"), "market": row.get("market"), "name": row.get("name"),
        "rank": rank, "attention_score": row.get("attention_score"),
        "reason": "新進前十；" + "；".join((row.get("ranking_evidence") or [])[:2]),
    } for rank, row in enumerate(new, 1) if (str(row.get("symbol")), str(row.get("market"))) not in old_map]
    exited = [{
        "symbol": row.get("symbol"), "market": row.get("market"), "name": row.get("name"),
        "previous_rank": rank, "previous_attention_score": row.get("attention_score"),
        "reason": "未進入本次前十；可能由分數、同產業上限或資料狀態變化造成。",
    } for rank, row in enumerate(old[:limit], 1) if (str(row.get("symbol")), str(row.get("market"))) not in new_map]
    retained = []
    for new_rank, row in enumerate(new, 1):
        key = (str(row.get("symbol")), str(row.get("market")))
        if key not in old_map:
            continue
        old_rank = next(index for index, item in enumerate(old[:limit], 1)
                        if (str(item.get("symbol")), str(item.get("market"))) == key)
        retained.append({"symbol": row.get("symbol"), "market": row.get("market"),
                         "previous_rank": old_rank, "rank": new_rank,
                         "rank_change": old_rank - new_rank})
    denominator = max(len(old[:limit]), len(new), 1)
    turnover = round(max(len(entered), len(exited)) / denominator * 100, 2) if old else 0.0
    return {"entered": entered, "exited": exited, "retained": retained,
            "turnover_percent": turnover}


def _compact_signal(row: dict | None) -> dict | None:
    if not row:
        return None
    plan = row.get("trade_plan") or {}
    return {
        "symbol": row.get("symbol"),
        "market": row.get("market"),
        "name": row.get("name"),
        "close": row.get("close"),
        "latest_price_date": row.get("latest_price_date"),
        "operation_status": row.get("operation_status"),
        "operation_reason": row.get("operation_reason"),
        "attention_score": row.get("attention_score"),
        "operation_gap": row.get("operation_gap") or {},
        "trigger_checks": row.get("trigger_checks")
        or (row.get("trade_plan") or {}).get("trigger_checks")
        or {},
        "trade_plan": {
            "reference_entry": plan.get("reference_entry"),
            "stop": plan.get("stop"),
            "planned_target": plan.get("planned_target"),
        },
    }


def _signal_follow_up(previous: dict | None, current: dict) -> dict:
    """Compare the prior ready list with today's status without implying a trade."""
    current_date = _iso_date(current.get("signal_date"))
    previous_date = _iso_date((previous or {}).get("signal_date"))
    previous_ready = (previous or {}).get("operation_ready_candidates") or []
    current_ready = current.get("operation_ready_candidates") or []
    tracked = current.get("tracked_candidate_statuses") or []

    current_map = {
        (str(row.get("symbol")), str(row.get("market"))): row
        for row in [*tracked, *current_ready]
        if row.get("symbol")
    }
    previous_keys = {
        (str(row.get("symbol")), str(row.get("market"))) for row in previous_ready
    }
    new_trigger_symbols = [
        str(row.get("symbol")) for row in current_ready
        if (str(row.get("symbol")), str(row.get("market"))) not in previous_keys
    ]

    continued, expired = [], []
    lifecycle = {
        "ready": ("continued_ready", "持續有效"),
        "ready_with_risk": ("continued_with_risk", "持續有效但有風險"),
        "waiting_trigger": ("waiting_retrigger", "等待重新觸發"),
        "reject_rr": ("invalidated_rr", "風險報酬失效"),
        "blocked_overextended": ("blocked_overextended", "短線過度延伸"),
        "blocked_fundamental": ("blocked_fundamental", "基本面條件失效"),
        "blocked": ("blocked", "風險條件阻擋"),
    }
    for prior in previous_ready:
        key = (str(prior.get("symbol")), str(prior.get("market")))
        now = current_map.get(key)
        status = str((now or {}).get("operation_status") or "not_eligible")
        lifecycle_status, lifecycle_label = lifecycle.get(
            status, ("not_eligible", "不在今日合格名單")
        )
        item = {
            "symbol": prior.get("symbol"),
            "market": prior.get("market"),
            "name": prior.get("name"),
            "previous": _compact_signal(prior),
            "current": _compact_signal(now),
            "lifecycle_status": lifecycle_status,
            "lifecycle_label": lifecycle_label,
            "reason": (now or {}).get("operation_reason")
            or "今日已不在基本面與技術候選名單",
        }
        if status in {"ready", "ready_with_risk"}:
            continued.append(item)
        else:
            expired.append(item)

    return {
        "available": bool(previous_date and current_date and previous_date < current_date),
        "previous_signal_date": previous_date,
        "current_signal_date": current_date,
        "previous_ready_count": len(previous_ready),
        "new_trigger_symbols": new_trigger_symbols,
        "continued_signals": continued,
        "expired_signals": expired,
        "position_notice": "此處追蹤訊號，不代表已成交；實際持倉仍以使用者持股紀錄為準。",
    }


def _latest_published_result(database: Database, strategy_version: str = STRATEGY_VERSION) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT result_json,signal_date,created_at,turnover_percent,changes_json
               FROM short_term_ranking_runs WHERE strategy_version=?
               ORDER BY signal_date DESC,id DESC LIMIT 1""",
            (strategy_version,),
        ).fetchone()
    if not row:
        return None
    result = json.loads(row["result_json"])
    result["published_at"] = row["created_at"]
    result["turnover_percent"] = row["turnover_percent"]
    result["ranking_changes"] = json.loads(row["changes_json"] or "{}")
    return result


def _published_result_before(
    database: Database,
    signal_date: str,
    strategy_version: str = STRATEGY_VERSION,
) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT result_json,signal_date,created_at,turnover_percent,changes_json
               FROM short_term_ranking_runs
               WHERE strategy_version=? AND signal_date<?
               ORDER BY signal_date DESC,id DESC LIMIT 1""",
            (strategy_version, signal_date),
        ).fetchone()
    if not row:
        return None
    result = json.loads(row["result_json"])
    result["published_at"] = row["created_at"]
    result["turnover_percent"] = row["turnover_percent"]
    result["ranking_changes"] = json.loads(row["changes_json"] or "{}")
    return result


def _ready_symbols(result: dict | None) -> set[str]:
    return {
        str(row.get("symbol"))
        for row in (result or {}).get("operation_ready_candidates") or []
        if row.get("symbol")
    }


def _revalidate_cached_data_pending(database: Database, result: dict) -> dict:
    """Refresh operational sync warnings without rewriting the saved ranking."""
    pending_rows = result.get("fundamental_data_pending") or []
    if not pending_rows:
        return result
    still_pending = []
    resolved = []
    for item in pending_rows:
        symbol = str(item.get("symbol") or "")
        market = str(item.get("market") or "")
        price_date = _iso_date(item.get("latest_price_date"))
        close = _number(item.get("close"))
        if not symbol or not market or not price_date or close is None:
            still_pending.append(item)
            continue
        assessment = load_short_term_fundamental_assessment(
            database, symbol, market, price_date, close
        )
        if assessment.get("status") == "data_pending":
            still_pending.append({**item, "fundamental_snapshot": assessment})
        else:
            resolved.append(symbol)
    return {
        **result,
        "fundamental_data_pending": still_pending,
        "resolved_data_pending_symbols": resolved,
    }


def _historical_market_context(database: Database, signal_date: str) -> dict | None:
    """Rebuild only the market fields that were knowable on the saved signal date."""
    with database.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT trade_date,close,market_score,overheat_score,regime
               FROM market_index_snapshots WHERE trade_date<=?
               ORDER BY trade_date DESC LIMIT 61""",
            (signal_date,),
        )]
    if not rows or rows[0]["trade_date"] != signal_date:
        return None
    rows.reverse()
    closes = [float(row["close"]) for row in rows]

    def change(days: int) -> float | None:
        return ((closes[-1] / closes[-days - 1] - 1) * 100
                if len(closes) > days else None)

    latest = rows[-1]
    return {
        "available": True,
        "as_of": signal_date,
        "index_close": float(latest["close"]),
        "market_score": _number(latest.get("market_score")),
        "overheat_score": _number(latest.get("overheat_score")),
        "regime": latest.get("regime") or "歷史市場狀態",
        "index_change_5d": change(5),
        "index_change_20d": change(20),
        "events": [],
        "sources": ["market_index_snapshots point-in-time reconstruction"],
        "historical_reconstruction": True,
    }


def published_short_term_decisions(
    database: Database,
    context: dict,
    as_of_date: date | None = None,
    limit: int = 10,
    *,
    result: dict | None = None,
) -> dict:
    """Return live rankings only when complete; otherwise keep the last valid run."""
    as_of_date = as_of_date or date.today()
    if result is None:
        cached = _latest_published_result(database)
        context_date = _iso_date(context.get("as_of"))
        cached_signal_date = _iso_date(cached.get("signal_date")) if cached else None
        if cached and (context_date is None or cached_signal_date == context_date):
            cached_gate = ranking_publication_gate(database, cached, context)
            if cached_gate["ready"]:
                cached = _revalidate_cached_data_pending(database, cached)
                if "signal_follow_up" not in cached and cached_signal_date:
                    previous = _published_result_before(database, cached_signal_date)
                    cached["signal_follow_up"] = _signal_follow_up(previous, cached)
                return {
                    **cached,
                    "publication_status": "ready",
                    "publication_gate": cached_gate,
                    "ranking_is_stale": False,
                    "served_from_snapshot": True,
                }
    previous = _latest_published_result(database)
    live = result or build_short_term_decisions(
        database,
        context,
        as_of_date,
        limit,
        tracked_symbols=_ready_symbols(previous),
    )
    live_signal_date = _iso_date(live.get("signal_date"))
    comparison_previous = previous
    if (
        comparison_previous
        and live_signal_date
        and _iso_date(comparison_previous.get("signal_date")) >= live_signal_date
    ):
        comparison_previous = _published_result_before(database, live_signal_date)
    live["signal_follow_up"] = _signal_follow_up(comparison_previous, live)
    gate = ranking_publication_gate(database, live, context)
    if gate["ready"]:
        return {**live, "publication_status": "ready", "publication_gate": gate,
                "ranking_is_stale": False}
    previous = _latest_published_result(
        database, live.get("strategy_version") or STRATEGY_VERSION
    )
    if previous:
        previous = _revalidate_cached_data_pending(database, previous)
        return {
            **previous,
            "publication_status": "held_previous",
            "publication_gate": gate,
            "ranking_is_stale": True,
            "requested_as_of_date": as_of_date.isoformat(),
            "live_candidate_signal_date": live.get("signal_date"),
            "stale_reason": "今日資料尚未完整，沿用上一份通過完整性檢查的榜單。",
        }
    empty = dict(live)
    for key in ("decisions", "observation_rankings", "attention_rankings",
                "operation_ready_candidates", "closest_operation_candidates",
                "analysis_pass_candidates", "execution_candidates"):
        empty[key] = []
    return {**empty, "publication_status": "unavailable", "publication_gate": gate,
            "ranking_is_stale": True,
            "stale_reason": "今日資料尚未完整，且目前沒有可沿用的有效榜單。"}


def capture_short_term_ranking_snapshot(
    database: Database,
    context: dict,
    as_of_date: date | None = None,
    *,
    result: dict | None = None,
    limit: int = 10,
) -> dict:
    """Persist one immutable, fully aligned Top 10 run per signal date."""
    as_of_date = as_of_date or date.today()
    previous = _latest_published_result(database)
    result = result or build_short_term_decisions(
        database,
        context,
        as_of_date,
        limit,
        tracked_symbols=_ready_symbols(previous),
    )
    signal_date = result.get("signal_date")
    comparison_previous = previous
    if (
        comparison_previous
        and signal_date
        and _iso_date(comparison_previous.get("signal_date")) >= _iso_date(signal_date)
    ):
        comparison_previous = _published_result_before(database, _iso_date(signal_date))
    result["signal_follow_up"] = _signal_follow_up(comparison_previous, result)
    rankings = (result.get("attention_rankings") or [])[:limit]
    gate = ranking_publication_gate(database, result, context)
    if not gate["ready"]:
        bootstrap = None
        strategy_version = result.get("strategy_version") or STRATEGY_VERSION
        if signal_date and not _latest_published_result(database, strategy_version):
            historical_context = _historical_market_context(database, signal_date)
            if historical_context:
                historical_result = build_short_term_decisions(
                    database, historical_context, date.fromisoformat(signal_date), limit
                )
                historical_gate = ranking_publication_gate(
                    database, historical_result, historical_context
                )
                if historical_gate["ready"]:
                    bootstrap = capture_short_term_ranking_snapshot(
                        database, historical_context, date.fromisoformat(signal_date),
                        result=historical_result, limit=limit,
                    )
        return {"status": "partial", "publication_status": "held_previous",
                "signal_date": signal_date, "rows_written": 0,
                "publication_gate": gate, "bootstrap": bootstrap}
    if not signal_date or not rankings:
        return {"status": "empty", "signal_date": signal_date, "rows_written": 0}

    strategy_version = result.get("strategy_version") or STRATEGY_VERSION
    with database.connect() as connection:
        existing = connection.execute(
            """SELECT id,turnover_percent,changes_json FROM short_term_ranking_runs
               WHERE signal_date=? AND strategy_version=?""",
            (signal_date, strategy_version),
        ).fetchone()
    if existing:
        return {"status": "completed", "publication_status": "already_published",
                "signal_date": signal_date, "strategy_version": strategy_version,
                "rows_written": 0, "turnover_percent": existing["turnover_percent"],
                "changes": json.loads(existing["changes_json"] or "{}"),
                "publication_gate": gate}

    previous = _latest_published_result(database, strategy_version)
    changes = _ranking_changes(previous, result, limit)

    eligible = short_term_fundamental_candidates(database, date.fromisoformat(signal_date))
    eligible = [row for row in eligible if str(row.get("latest_price_date")) == signal_date]
    peers_by_industry: dict[str, list[dict]] = {}
    for row in eligible:
        industry = row.get("industry") or "未分類"
        peers_by_industry.setdefault(industry, []).append({
            "symbol": row["symbol"], "market": row["market"],
        })

    market_close = (_number(context.get("index_close"))
                    if result.get("market_data_aligned") else None)
    payload = []
    for rank, item in enumerate(rankings, 1):
        close = _number(item.get("close"))
        if close is None:
            continue
        industry = item.get("industry") or "未分類"
        evidence = {
            "attention_score_components": item.get("attention_score_components") or {},
            "ranking_evidence": item.get("ranking_evidence") or [],
            "ranking_risks": item.get("ranking_risks") or [],
            "operation_reason": item.get("operation_reason"),
            "operation_gap": item.get("operation_gap") or {},
            "trigger_checks": item.get("trade_plan", {}).get("trigger_checks") or {},
            "data_as_of": item.get("data_as_of") or {},
        }
        payload.append((
            item["symbol"], item["market"], item.get("name"), industry, rank,
            item.get("attention_grade") or item.get("candidate_grade") or "D",
            _number(item.get("attention_score")) or 0,
            item.get("operation_status") or "blocked", close, market_close,
            result.get("market_mode"),
            json.dumps(peers_by_industry.get(industry, []), ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False, default=str),
            json.dumps(item, ensure_ascii=False, default=str),
        ))
    with database.connect() as connection:
        cursor = connection.execute(
            """INSERT INTO short_term_ranking_runs
               (signal_date,requested_date,strategy_version,market_date,coverage_json,
                result_json,turnover_percent,changes_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (signal_date, result.get("as_of_date") or as_of_date.isoformat(),
             strategy_version, gate.get("target_date"),
             json.dumps(gate, ensure_ascii=False, default=str),
             json.dumps(result, ensure_ascii=False, default=str),
             changes["turnover_percent"], json.dumps(changes, ensure_ascii=False, default=str)),
        )
        run_id = cursor.lastrowid
        connection.executemany(
            """INSERT INTO short_term_ranking_run_items
               (run_id,symbol,market,name,industry,rank,attention_grade,
                attention_score,operation_status,signal_close,market_close,market_mode,
                peer_symbols_json,payload_json,item_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(run_id, *row) for row in payload],
        )
    return {
        "status": "completed", "publication_status": "published",
        "signal_date": signal_date, "strategy_version": strategy_version,
        "rows_written": len(payload), "turnover_percent": changes["turnover_percent"],
        "changes": changes, "publication_gate": gate,
    }


def _forward_path(rows: list[dict], signal_date: str, entry: float, horizon: int) -> dict:
    future = [row for row in rows if row["trade_date"] > signal_date]
    if len(future) < horizon:
        return {"matured": False, "target_date": None, "return_percent": None,
                "max_drawdown_percent": None, "max_runup_percent": None}
    path = future[:horizon]
    closes = [float(row["close"]) for row in path]
    gross_return = (closes[-1] / entry - 1) * 100
    return {
        "matured": True,
        "target_date": path[-1]["trade_date"],
        "return_percent": round(gross_return, 4),
        "net_return_after_assumed_cost_percent": round(
            gross_return - ASSUMED_ROUND_TRIP_COST_PERCENT, 4
        ),
        "max_drawdown_percent": round(min(value / entry - 1 for value in closes) * 100, 4),
        "max_runup_percent": round(max(value / entry - 1 for value in closes) * 100, 4),
    }


def _peer_return(
    price_map: dict[tuple[str, str], list[dict]],
    peers: list[dict],
    subject: tuple[str, str],
    signal_date: str,
    horizon: int,
) -> tuple[float | None, int]:
    returns = []
    for peer in peers:
        key = (str(peer.get("symbol")), str(peer.get("market")))
        if key == subject:
            continue
        rows = price_map.get(key, [])
        history = [row for row in rows if row["trade_date"] <= signal_date]
        if not history:
            continue
        outcome = _forward_path(rows, signal_date, float(history[-1]["close"]), horizon)
        if outcome["matured"]:
            returns.append(outcome["return_percent"])
    return (round(median(returns), 4), len(returns)) if len(returns) >= 3 else (None, len(returns))


def _forward_effectiveness_assessment(outcomes: list[dict], summaries: dict) -> dict:
    """State whether immutable forward snapshots are sufficient to judge the ranking."""
    eligible_horizons: list[str] = []
    supported_horizons: list[str] = []
    details = []
    for horizon in HORIZONS:
        key = str(horizon)
        row = summaries[key]
        unique_signal_dates = len({
            item["signal_date"] for item in outcomes
            if item["horizons"][key].get("matured")
        })
        row["unique_signal_dates"] = unique_signal_dates
        enough_samples = (
            row["matured_signals"] >= MIN_FORWARD_MATURED_SIGNALS
            and unique_signal_dates >= MIN_FORWARD_SIGNAL_DATES
        )
        net_positive = (
            row.get("average_net_return_after_assumed_cost_percent") is not None
            and row["average_net_return_after_assumed_cost_percent"] > 0
        )
        market_excess_positive = (
            row.get("average_market_excess_return_percent") is not None
            and row["average_market_excess_return_percent"] > 0
        )
        industry_excess_positive = (
            row.get("average_industry_excess_return_percent") is not None
            and row["average_industry_excess_return_percent"] > 0
        )
        supported = (
            enough_samples and net_positive
            and market_excess_positive and industry_excess_positive
        )
        if enough_samples:
            eligible_horizons.append(key)
        if supported:
            supported_horizons.append(key)
        details.append({
            "horizon_sessions": horizon,
            "matured_signals": row["matured_signals"],
            "unique_signal_dates": unique_signal_dates,
            "enough_samples": enough_samples,
            "net_return_after_cost_positive": net_positive,
            "market_excess_positive": market_excess_positive,
            "industry_excess_positive": industry_excess_positive,
            "supported": supported,
        })
    if not eligible_horizons:
        verdict = "insufficient_data"
    elif len(supported_horizons) >= 2:
        verdict = "promising_not_yet_validated"
    elif supported_horizons:
        verdict = "mixed_evidence"
    else:
        verdict = "forward_evidence_does_not_support_ranking"
    return {
        "verdict": verdict,
        "eligible_horizons": eligible_horizons,
        "supported_horizons": supported_horizons,
        "minimum_matured_signals_per_horizon": MIN_FORWARD_MATURED_SIGNALS,
        "minimum_signal_dates_per_horizon": MIN_FORWARD_SIGNAL_DATES,
        "criteria": (
            "扣除假設成本後平均報酬、大盤超額與同業超額必須同時為正，"
            "且至少兩個持有期達到最低樣本數。"
        ),
        "details": details,
        "formal_validation_allowed": False,
        "reason": "前瞻追蹤仍須與嚴格 point-in-time 歷史回放一致後才能升級為正式策略。",
    }


def short_term_ranking_tracking(
    database: Database,
    *,
    strategy_version: str = STRATEGY_VERSION,
    snapshot_limit: int = 300,
) -> dict:
    """Evaluate saved lists only after each forward horizon has actually matured."""
    with database.connect() as connection:
        run_rows = [dict(row) for row in connection.execute(
            """SELECT id,signal_date,requested_date,strategy_version,market_date,
                      turnover_percent,changes_json,created_at
               FROM short_term_ranking_runs WHERE strategy_version=?
               ORDER BY signal_date DESC,id DESC""",
            (strategy_version,),
        )]
        snapshots = [dict(row) for row in connection.execute(
            """SELECT r.signal_date,r.requested_date,r.strategy_version,
                      i.symbol,i.market,i.name,i.industry,i.rank,i.attention_grade,
                      i.attention_score,i.operation_status,i.signal_close,
                      i.market_close,i.market_mode,i.peer_symbols_json,i.payload_json,
                      r.created_at
               FROM short_term_ranking_run_items i
               JOIN short_term_ranking_runs r ON r.id=i.run_id
               WHERE r.strategy_version=?
               ORDER BY r.signal_date DESC,i.rank LIMIT ?""",
            (strategy_version, snapshot_limit),
        )]
        if not snapshots:
            snapshots = [dict(row) for row in connection.execute(
                """SELECT * FROM short_term_ranking_snapshots
                   WHERE strategy_version=?
                   ORDER BY signal_date DESC, rank LIMIT ?""",
                (strategy_version, snapshot_limit),
            )]
    if not snapshots:
        return {
            "strategy_version": strategy_version, "snapshot_dates": [],
            "total_signals": 0, "horizons": {}, "outcomes": [],
            "limitations": ["尚未保存任何每日排行榜快照。"],
        }

    peer_sets = [json.loads(row["peer_symbols_json"] or "[]") for row in snapshots]
    keys = {(row["symbol"], row["market"]) for row in snapshots}
    keys.update((str(peer.get("symbol")), str(peer.get("market")))
                for peers in peer_sets for peer in peers)
    earliest = min(row["signal_date"] for row in snapshots)
    price_map: dict[tuple[str, str], list[dict]] = {}
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT symbol,market,trade_date,close FROM daily_prices
               WHERE trade_date>=date(?, '-14 days') ORDER BY symbol,market,trade_date""",
            (earliest,),
        )
        for row in rows:
            item = dict(row)
            key = (item["symbol"], item["market"])
            if key in keys:
                price_map.setdefault(key, []).append(item)
        index_rows = [dict(row) for row in connection.execute(
            """SELECT trade_date,close FROM market_index_snapshots
               WHERE trade_date>=date(?, '-14 days') ORDER BY trade_date""",
            (earliest,),
        )]

    outcomes = []
    for snapshot, peers in zip(snapshots, peer_sets):
        key = (snapshot["symbol"], snapshot["market"])
        horizons = {}
        for horizon in HORIZONS:
            outcome = _forward_path(
                price_map.get(key, []), snapshot["signal_date"],
                float(snapshot["signal_close"]), horizon,
            )
            benchmark = None
            if outcome["matured"] and snapshot.get("market_close"):
                benchmark_path = _forward_path(
                    index_rows, snapshot["signal_date"], float(snapshot["market_close"]), horizon
                )
                if benchmark_path["matured"]:
                    benchmark = benchmark_path["return_percent"]
            industry_return, peer_count = _peer_return(
                price_map, peers, key, snapshot["signal_date"], horizon
            ) if outcome["matured"] else (None, 0)
            outcome["market_return_percent"] = benchmark
            outcome["market_excess_return_percent"] = (
                round(outcome["return_percent"] - benchmark, 4)
                if outcome["matured"] and benchmark is not None else None
            )
            outcome["industry_median_return_percent"] = industry_return
            outcome["industry_excess_return_percent"] = (
                round(outcome["return_percent"] - industry_return, 4)
                if outcome["matured"] and industry_return is not None else None
            )
            outcome["industry_peer_count"] = peer_count
            horizons[str(horizon)] = outcome
        evidence = json.loads(snapshot.pop("payload_json") or "{}")
        snapshot.pop("peer_symbols_json", None)
        outcomes.append({**snapshot, "evidence": evidence, "horizons": horizons})

    summaries = {}
    for horizon in HORIZONS:
        rows = [item["horizons"][str(horizon)] for item in outcomes]
        matured = [row for row in rows if row["matured"]]
        returns = [row["return_percent"] for row in matured]
        net_returns = [row["net_return_after_assumed_cost_percent"] for row in matured]
        market_excess = [row["market_excess_return_percent"] for row in matured
                         if row["market_excess_return_percent"] is not None]
        industry_excess = [row["industry_excess_return_percent"] for row in matured
                           if row["industry_excess_return_percent"] is not None]
        summaries[str(horizon)] = {
            "matured_signals": len(matured), "pending_signals": len(rows) - len(matured),
            "win_rate_percent": round(sum(value > 0 for value in returns) / len(returns) * 100, 2)
                if returns else None,
            "average_return_percent": round(mean(returns), 4) if returns else None,
            "median_return_percent": round(median(returns), 4) if returns else None,
            "average_net_return_after_assumed_cost_percent": round(mean(net_returns), 4)
                if net_returns else None,
            "average_market_excess_return_percent": round(mean(market_excess), 4)
                if market_excess else None,
            "average_industry_excess_return_percent": round(mean(industry_excess), 4)
                if industry_excess else None,
            "average_max_drawdown_percent": round(mean(
                row["max_drawdown_percent"] for row in matured
            ), 4) if matured else None,
        }
    effectiveness_assessment = _forward_effectiveness_assessment(outcomes, summaries)
    return {
        "strategy_version": strategy_version,
        "snapshot_dates": sorted({row["signal_date"] for row in snapshots}, reverse=True),
        "total_signals": len(outcomes), "horizons": summaries, "outcomes": outcomes,
        "effectiveness_assessment": effectiveness_assessment,
        "ranking_runs": [{
            **{key: row.get(key) for key in (
                "signal_date", "requested_date", "market_date", "turnover_percent", "created_at"
            )},
            "changes": json.loads(row.get("changes_json") or "{}"),
        } for row in run_rows],
        "latest_turnover_percent": run_rows[0].get("turnover_percent") if run_rows else None,
        "cost_assumption_percent": ASSUMED_ROUND_TRIP_COST_PERCENT,
        "method": "以保存當日排行榜的訊號日收盤為研究基準，觀察之後第 3／5／10 個交易日收盤；未成熟樣本不計為 0%。",
        "limitations": [
            "這是從保存日起的前瞻追蹤，不是回填歷史榜單，也不是獲利證明。",
            "成本後報酬固定扣除 0.785%；真實次日開盤、券商折扣與市場衝擊可能不同。",
            "產業比較使用快照當時通過基本面門檻的同業名單，中位數至少需要 3 檔成熟同業。",
        ],
    }
