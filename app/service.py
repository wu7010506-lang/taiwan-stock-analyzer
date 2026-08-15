from datetime import date
from collections import Counter
from time import sleep

import httpx

from app.config import settings
from app.database import Database
from app.providers import TpexProvider, TwseProvider


def _twse_ranking_candidate_symbols(database: Database, target_date: date) -> list[str]:
    """Select only stocks that can enter the ranking before doing per-symbol I/O."""
    from app.short_term_decision import short_term_fundamental_candidates

    return sorted({
        str(row["symbol"])
        for row in short_term_fundamental_candidates(database, target_date)
        if row.get("market") == "TWSE" and row.get("symbol")
    })


def sync_twse_candidate_price_fallback(
    database: Database,
    target_date: date,
    *,
    symbols: list[str] | None = None,
    pause_seconds: float = 0.05,
) -> dict:
    """Fill stale ranking candidates from TWSE's official per-symbol month table."""
    symbols = list(dict.fromkeys(symbols or _twse_ranking_candidate_symbols(
        database, target_date
    )))
    if not symbols:
        return {
            "status": "empty", "source": "TWSE official per-symbol STOCK_DAY",
            "target_date": target_date.isoformat(), "requested_symbols": 0,
            "target_date_symbols": 0, "rows_written": 0,
            "coverage_percent": 0.0, "errors": [],
        }
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    written = 0
    completed_symbols: list[str] = []
    errors = []
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers,
                      follow_redirects=True) as client:
        provider = TwseProvider(client)
        for index, symbol in enumerate(symbols):
            try:
                rows = provider.fetch_history_month(symbol, target_date.replace(day=1))
                rows = [row for row in rows if row.trade_date <= target_date]
                target_rows = [row for row in rows
                               if row.trade_date == target_date and float(row.close) > 0]
                if not target_rows:
                    errors.append({"symbol": symbol, "error": "target_date_not_available"})
                    continue
                written += database.upsert_prices(rows)
                completed_symbols.append(symbol)
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)[:300]})
            if pause_seconds > 0 and index + 1 < len(symbols):
                sleep(pause_seconds)
    coverage = round(len(completed_symbols) / len(symbols) * 100, 2)
    return {
        "status": "completed" if coverage >= 95 else "partial",
        "source": "TWSE official per-symbol STOCK_DAY",
        "target_date": target_date.isoformat(),
        "requested_symbols": len(symbols),
        "target_date_symbols": len(completed_symbols),
        "rows_written": written,
        "coverage_percent": coverage,
        "completed_symbols": completed_symbols,
        "errors": errors,
        "same_volume_scope_as_primary": True,
        "limitation": "Official per-symbol endpoint has no published completion-time SLA; coverage gate still applies.",
    }


def sync_market_data(database: Database) -> dict[str, dict[str, int | str]]:
    result: dict[str, dict[str, int | str]] = {}
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers, follow_redirects=True) as client:
        for provider in (TwseProvider(client), TpexProvider(client)):
            try:
                instruments = provider.fetch_instruments()
                prices = provider.fetch_latest_prices()
                date_counts = Counter(row.trade_date.isoformat() for row in prices)
                data_date = (max(date_counts, key=lambda value: (date_counts[value], value))
                             if date_counts else None)
                result[provider.market] = {
                    "instruments": database.upsert_instruments(instruments),
                    "prices": database.upsert_prices(prices),
                    "status": "fetched",
                    "source": f"{provider.market} official API",
                    "fallback_used": False,
                    "data_date": data_date,
                    "date_distribution": dict(sorted(date_counts.items(), reverse=True)),
                    "dominant_date_coverage_percent": (
                        round(date_counts[data_date] / len(prices) * 100, 2)
                        if data_date and prices else 0.0
                    ),
                }
            except Exception as exc:  # 保留另一市場繼續更新
                cached = database.get_market_cached_counts(provider.market)
                fallback_used = bool(cached["instruments"] or cached["prices"])
                result[provider.market] = {
                    **cached,
                    "status": "cached" if fallback_used else "failed",
                    "source": "local cache" if fallback_used else None,
                    "fallback_used": fallback_used,
                    "error": str(exc),
                }
    failures = [market for market, item in result.items() if item.get("error")]
    market_dates = [result[market].get("data_date") for market in ("TWSE", "TPEx")
                    if result.get(market, {}).get("data_date")]
    target_date = max(market_dates) if market_dates else None
    if (target_date and result.get("TWSE", {}).get("data_date")
            and result["TWSE"]["data_date"] < target_date):
        result["TWSE"]["candidate_fallback"] = sync_twse_candidate_price_fallback(
            database, date.fromisoformat(target_date)
        )
    incomplete = [market for market in ("TWSE", "TPEx")
                  if result.get(market, {}).get("data_date") != target_date]
    result["status"] = "completed" if not failures and not incomplete else "partial"
    result["failed_markets"] = failures
    result["target_data_date"] = target_date
    result["incomplete_markets"] = incomplete
    return result


def _months_between(start: date, end: date) -> list[date]:
    months = []
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while current <= last:
        months.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return months


def sync_history(database: Database, symbol: str, start: date, end: date) -> dict:
    if start > end:
        raise ValueError("start 不可晚於 end")
    if end > date.today():
        raise ValueError("end 不可晚於今天")
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError("找不到股票代號；請先執行 POST /sync")
    months = _months_between(start, end)
    run_id = database.create_sync_run(
        symbol, instrument["market"], start.isoformat(), end.isoformat(), len(months)
    )
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    rows_written = 0
    completed = 0
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers, follow_redirects=True) as client:
            provider = TwseProvider(client) if instrument["market"] == "TWSE" else TpexProvider(client)
            for month in months:
                rows = [
                    row
                    for row in provider.fetch_history_month(symbol, month)
                    if start <= row.trade_date <= end
                ]
                rows_written += database.upsert_prices(rows)
                completed += 1
                database.update_sync_run(run_id, completed, rows_written)
    except Exception as exc:
        database.update_sync_run(run_id, completed, rows_written, "failed", str(exc))
        raise
    database.update_sync_run(run_id, completed, rows_written, "completed")
    return {
        "run_id": run_id,
        "symbol": symbol,
        "market": instrument["market"],
        "start": start,
        "end": end,
        "months_completed": completed,
        "rows_written": rows_written,
        "status": "completed",
    }
