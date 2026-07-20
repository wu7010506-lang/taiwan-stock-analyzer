from datetime import date

import httpx

from app.config import settings
from app.database import Database
from app.providers import TpexProvider, TwseProvider


def sync_market_data(database: Database) -> dict[str, dict[str, int | str]]:
    result: dict[str, dict[str, int | str]] = {}
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers) as client:
        for provider in (TwseProvider(client), TpexProvider(client)):
            try:
                instruments = provider.fetch_instruments()
                prices = provider.fetch_latest_prices()
                result[provider.market] = {
                    "instruments": database.upsert_instruments(instruments),
                    "prices": database.upsert_prices(prices),
                }
            except Exception as exc:  # 保留另一市場繼續更新
                result[provider.market] = {"error": str(exc)}
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
        with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers) as client:
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
