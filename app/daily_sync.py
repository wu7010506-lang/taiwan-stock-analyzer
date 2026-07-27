from __future__ import annotations

import json
from datetime import datetime

import httpx

from app.config import settings
from app.database import Database
from app.institutions import _integer, normalize_tpex
from app.market_context import get_market_context
from app.providers import _parse_date
from app.screening import sync_screening_universe
from app.service import sync_market_data
from app.performance import capture_recommendation_snapshots
from app.analysis_sync import sync_watchlist_analysis_data
from app.vnext_model import recommend_vnext_stocks


def _sync_watchlist_with_retry(database: Database) -> dict:
    """Retry only incomplete watchlist datasets once for transient provider failures."""
    first = sync_watchlist_analysis_data(database)
    if first["status"] == "completed":
        return {**first, "retry_attempted": False}
    retry = sync_watchlist_analysis_data(database)
    return {**retry, "retry_attempted": True,
            "first_attempt_partial": first["partial"],
            "retry_recovered": max(0, first["partial"] - retry["partial"])}


def sync_all_institutional_trades(database: Database) -> dict:
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    rows, errors = [], []
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers,
                      follow_redirects=True) as client:
        try:
            response = client.get("https://www.twse.com.tw/rwd/zh/fund/T86",
                                  params={"response": "json", "selectType": "ALLBUT0999"})
            response.raise_for_status()
            payload = response.json()
            fields = payload.get("fields", [])
            trade_date = _parse_date(str(payload["date"])).isoformat()
            for values in payload.get("data", []):
                source = dict(zip(fields, values))
                symbol = str(source.get("證券代號", "")).strip()
                if symbol:
                    rows.append({"symbol": symbol, "market": "TWSE", "trade_date": trade_date,
                        "foreign_buy": _integer(source.get("外陸資買進股數(不含外資自營商)")),
                        "foreign_sell": _integer(source.get("外陸資賣出股數(不含外資自營商)")),
                        "foreign_net": _integer(source.get("外陸資買賣超股數(不含外資自營商)")),
                        "trust_buy": _integer(source.get("投信買進股數")),
                        "trust_sell": _integer(source.get("投信賣出股數")),
                        "trust_net": _integer(source.get("投信買賣超股數")),
                        "source": "TWSE 三大法人買賣超日報"})
        except Exception as exc:
            errors.append(f"TWSE: {exc}")
        try:
            response = client.get(
                "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading")
            response.raise_for_status()
            rows.extend(normalize_tpex(item) for item in response.json()
                        if item.get("SecuritiesCompanyCode") and item.get("Date"))
        except Exception as exc:
            errors.append(f"TPEx: {exc}")
    written = database.upsert_institutional_trades(rows) if rows else 0
    return {"rows_written": written, "errors": errors,
            "status": "completed" if not errors else "partial"}


def run_daily_close_sync(database: Database) -> dict:
    """Idempotent whole-market close job. Each step fails independently."""
    database.initialize()
    run_id = database.create_daily_sync_run()
    if run_id is None:
        return {"status": "already_running", "steps": {}}
    steps = {}
    operations = (
        ("market", lambda: sync_market_data(database)),
        ("fundamentals", lambda: sync_screening_universe(database)),
        ("institutions", lambda: sync_all_institutional_trades(database)),
        ("watchlist_analysis", lambda: _sync_watchlist_with_retry(database)),
        ("market_context", _market_context_summary),
        ("recommendation_snapshots", lambda: capture_recommendation_snapshots(
            database, get_market_context()
        )),
        ("vnext_recommendations", lambda: _capture_vnext_recommendations(database)),
        ("data_freshness", lambda: {
            "status": "completed", "markets": database.get_market_data_freshness(),
        }),
    )
    for name, operation in operations:
        steps[name] = {"status": "running"}
        database.update_daily_sync_progress(
            run_id, json.dumps(steps, ensure_ascii=False, default=str)
        )
        try:
            steps[name] = operation()
        except Exception as exc:
            steps[name] = {"status": "failed", "error": str(exc)}
        database.update_daily_sync_progress(
            run_id, json.dumps(steps, ensure_ascii=False, default=str)
        )
    failed = [name for name, result in steps.items()
              if isinstance(result, dict) and result.get("status") == "failed"]
    partial = [name for name, result in steps.items()
               if isinstance(result, dict) and result.get("status") == "partial"]
    status = "failed" if len(failed) == len(steps) else "partial" if failed or partial else "completed"
    error = "; ".join(failed + partial) or None
    database.finish_daily_sync_run(run_id, status,
                                   json.dumps(steps, ensure_ascii=False, default=str), error)
    return {"run_id": run_id, "status": status,
            "finished_at": datetime.now().isoformat(timespec="seconds"), "steps": steps}


def _capture_vnext_recommendations(database: Database) -> dict:
    result = recommend_vnext_stocks(database, datetime.now().date(), get_market_context(), 100)
    database.save_vnext_recommendation_run(
        result["as_of_date"], json.dumps(result, ensure_ascii=False, default=str)
    )
    return {"status": "completed", "as_of_date": result["as_of_date"],
            "recommendations": len(result.get("recommendations") or []),
            "universe_summary": result.get("universe_summary")}


def _market_context_summary() -> dict:
    context = get_market_context(force=True)
    return {"status": "completed" if context.get("available") else "partial",
            "available": context.get("available"), "as_of": context.get("as_of"),
            "market_score": context.get("market_score"), "regime": context.get("regime"),
            "event_count": len(context.get("events") or []),
            "errors": context.get("partial_errors") or []}


def latest_daily_sync(database: Database) -> dict:
    row = database.get_latest_daily_sync_run()
    if not row:
        return {"status": "never_run"}
    row["steps"] = json.loads(row.pop("steps_json") or "{}")
    return row
