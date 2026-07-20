from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from app.config import settings
from app.database import Database
from app.providers import ProviderError, _parse_date
from app.revenue import _iter_months


def _decimal(value: object) -> Decimal | None:
    text = str(value or "").replace(",", "").strip()
    if text in {"", "-", "--", "N/A"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ProviderError(f"估值數值格式異常：{value!r}") from exc


def fetch_valuation_date(
    client: httpx.Client, symbol: str, market: str, target: date
) -> dict | None:
    if market == "TWSE":
        url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
            f"?date={target:%Y%m%d}&selectType=ALL&response=json"
        )
    else:
        url = (
            "https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate"
            f"?date={target:%Y/%m/%d}&cate=&response=json"
        )
    try:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(f"{market} {target} 估值資料取得失敗：{exc}") from exc

    if market == "TWSE":
        if payload.get("stat") != "OK":
            return None
        row = next((item for item in payload.get("data", []) if item[0] == symbol), None)
        if not row:
            return None
        return {
            "symbol": symbol,
            "market": market,
            "valuation_date": payload.get("date", target.strftime("%Y%m%d")),
            "close_price": _decimal(row[2]),
            "dividend_yield": _decimal(row[3]),
            "dividend_year": str(row[4]),
            "pe_ratio": _decimal(row[5]),
            "pb_ratio": _decimal(row[6]),
            "financial_period": str(row[7]),
        }

    tables = payload.get("tables") or []
    if not tables:
        return None
    row = next((item for item in tables[0].get("data", []) if item[0] == symbol), None)
    if not row:
        return None
    return {
        "symbol": symbol,
        "market": market,
        "valuation_date": _parse_date(tables[0].get("date", target.isoformat())).strftime("%Y%m%d"),
        "close_price": None,
        "pe_ratio": _decimal(row[2]),
        "dividend_per_share": _decimal(row[3]),
        "dividend_year": str(row[4]),
        "dividend_yield": _decimal(row[5]),
        "pb_ratio": _decimal(row[6]),
        "financial_period": str(row[7]),
    }


def _percentile(values: list[float], current: float | None) -> float | None:
    if current is None or not values:
        return None
    return sum(value <= current for value in values) / len(values) * 100


def sync_valuations(database: Database, symbol: str, start: str, end: str) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError("找不到股票代號；請先更新全市場清單")
    months = _iter_months(start, end)
    today = date.today()
    written = 0
    missing = 0
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers, follow_redirects=True) as client:
        for year, month in months:
            last_day = calendar.monthrange(year, month)[1]
            target = min(date(year, month, last_day), today)
            row = None
            # 月底若為週末、假日或當月尚未收盤，向前尋找最近有資料的交易日。
            for offset in range(min(15, target.day)):
                candidate = target - timedelta(days=offset)
                row = fetch_valuation_date(
                    client, symbol, instrument["market"], candidate
                )
                if row:
                    break
            if row:
                database.upsert_valuation(row)
                written += 1
            else:
                missing += 1
    return {
        "symbol": symbol,
        "market": instrument["market"],
        "start": start,
        "end": end,
        "months_requested": len(months),
        "rows_written": written,
        "months_without_data": missing,
    }


def analyze_valuations(rows: list[dict]) -> dict:
    if not rows:
        return {}
    latest = rows[-1]
    pe_values = [float(row["pe_ratio"]) for row in rows if row["pe_ratio"] is not None]
    pb_values = [float(row["pb_ratio"]) for row in rows if row["pb_ratio"] is not None]
    yield_values = [
        float(row["dividend_yield"])
        for row in rows
        if row["dividend_yield"] is not None
    ]
    pe = float(latest["pe_ratio"]) if latest["pe_ratio"] is not None else None
    pb = float(latest["pb_ratio"]) if latest["pb_ratio"] is not None else None
    dividend_yield = (
        float(latest["dividend_yield"])
        if latest["dividend_yield"] is not None
        else None
    )
    pe_rank = _percentile(pe_values, pe)
    if pe_rank is None:
        relative_band = "資料不足"
    elif pe_rank <= 25:
        relative_band = "歷史相對低檔"
    elif pe_rank >= 75:
        relative_band = "歷史相對高檔"
    else:
        relative_band = "歷史中間區間"
    return {
        "symbol": latest["symbol"],
        "as_of": latest["valuation_date"],
        "pe_ratio": pe,
        "pb_ratio": pb,
        "dividend_yield": dividend_yield,
        "pe_percentile": pe_rank,
        "pb_percentile": _percentile(pb_values, pb),
        "dividend_yield_percentile": _percentile(yield_values, dividend_yield),
        "pe_min": min(pe_values) if pe_values else None,
        "pe_median": sorted(pe_values)[len(pe_values) // 2] if pe_values else None,
        "pe_max": max(pe_values) if pe_values else None,
        "relative_valuation_band": relative_band,
        "observations": len(rows),
        "financial_period": latest["financial_period"],
    }
