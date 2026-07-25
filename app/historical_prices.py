from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.config import settings
from app.database import Database
from app.domain import DailyPrice
from app.historical_fundamentals import _fetch


def normalize_finmind_prices(rows: list[dict], market: str) -> list[DailyPrice]:
    result = []
    for row in rows:
        try:
            close = Decimal(str(row.get("close")))
            opened = Decimal(str(row.get("open")))
            high = Decimal(str(row.get("max")))
            low = Decimal(str(row.get("min")))
            if close <= 0:
                continue
            result.append(DailyPrice(
                symbol=str(row["stock_id"]), market=market,
                trade_date=date.fromisoformat(str(row["date"])[:10]),
                open=opened, high=high, low=low, close=close,
                volume=int(float(row.get("Trading_Volume") or 0)),
                turnover=Decimal(str(row.get("Trading_money") or 0)),
                transaction_count=int(float(row.get("Trading_turnover") or 0)),
            ))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
    return result


def sync_finmind_price_history(database: Database, symbol: str, years: int = 3) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError(f"Stock {symbol} was not found")
    start_date = date(date.today().year - years, 1, 1).isoformat()
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers,
                      follow_redirects=True) as client:
        payload = _fetch(client, "TaiwanStockPrice", symbol, start_date)
    rows = normalize_finmind_prices(payload, instrument["market"])
    return {"symbol": symbol, "market": instrument["market"],
            "rows_written": database.upsert_prices(rows), "status": "completed"}
