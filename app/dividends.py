from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from app.config import settings
from app.database import Database
from app.providers import _parse_date


def _number(value: object) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(Decimal(text))
    except InvalidOperation:
        return None


def _normalize_twse(row: dict) -> dict:
    return {
        "symbol": str(row.get("Code", "")).strip(), "market": "TWSE",
        "ex_date": _parse_date(str(row["Date"])).isoformat(),
        "event_type": str(row.get("Exdividend", "")).strip() or "權息",
        "cash_dividend": _number(row.get("CashDividend")),
        "stock_dividend_ratio": _number(row.get("StockDividendRatio")),
        "source": "TWSE TWT48U_ALL",
    }


def _normalize_tpex(row: dict) -> dict:
    return {
        "symbol": str(row.get("SecuritiesCompanyCode", "")).strip(), "market": "TPEx",
        "ex_date": _parse_date(str(row["ExRrightsExDividendDate"])).isoformat(),
        "event_type": str(row.get("ExRrightsExDividend", "")).strip() or "權息",
        "cash_dividend": _number(row.get("CashDividend")),
        "stock_dividend_ratio": _number(row.get("StockDividendRatio")),
        "source": "TPEx tpex_exright_prepost",
    }


def sync_dividends(database: Database, symbol: str) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError("找不到股票代號；請先更新全市場清單")
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers) as client:
        if instrument["market"] == "TWSE":
            payload = client.get("https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL")
            payload.raise_for_status()
            rows = [_normalize_twse(row) for row in payload.json() if str(row.get("Code", "")).strip() == symbol]
        else:
            payload = client.get("https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost")
            payload.raise_for_status()
            rows = [_normalize_tpex(row) for row in payload.json() if str(row.get("SecuritiesCompanyCode", "")).strip() == symbol]
    return {"symbol": symbol, "rows_written": database.upsert_dividend_events(rows), "status": "completed"}
