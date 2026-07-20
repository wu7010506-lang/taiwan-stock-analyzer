from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import httpx

from app.config import settings
from app.database import Database
from app.providers import ProviderError


class _RevenueTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.in_cell:
            self.current_row.append("".join(self.current_cell).strip())
            self.in_cell = False
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []


def _decimal(text: str) -> Decimal | None:
    value = text.replace(",", "").strip()
    if value in {"", "-", "--"}:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ProviderError(f"月營收數值格式異常：{text!r}") from exc


def fetch_revenue_month(
    client: httpx.Client, symbol: str, market: str, year: int, month: int
) -> dict | None:
    roc_year = year - 1911
    category = "sii" if market == "TWSE" else "otc"
    url = (
        f"https://mopsov.twse.com.tw/nas/t21/{category}/"
        f"t21sc03_{roc_year}_{month}_0.html"
    )
    try:
        response = client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"MOPS {symbol} {year}-{month:02d} 月營收取得失敗：{exc}") from exc
    # 歷史頁面未固定宣告 charset；數字與股票代號皆為 ASCII，可安全忽略名稱亂碼。
    parser = _RevenueTableParser()
    parser.feed(response.content.decode("big5", errors="replace"))
    row = next((item for item in parser.rows if item and item[0].strip() == symbol), None)
    if not row or len(row) < 10:
        return None
    return {
        "symbol": symbol,
        "market": market,
        "revenue_month": f"{year:04d}-{month:02d}",
        "revenue": _decimal(row[2]),
        "previous_month_revenue": _decimal(row[3]),
        "previous_year_revenue": _decimal(row[4]),
        "mom_percent": _decimal(row[5]),
        "yoy_percent": _decimal(row[6]),
        "cumulative_revenue": _decimal(row[7]),
        "previous_year_cumulative_revenue": _decimal(row[8]),
        "cumulative_yoy_percent": _decimal(row[9]),
    }


def _iter_months(start: str, end: str) -> list[tuple[int, int]]:
    try:
        start_year, start_month = map(int, start.split("-"))
        end_year, end_month = map(int, end.split("-"))
        start_date = date(start_year, start_month, 1)
        end_date = date(end_year, end_month, 1)
    except (ValueError, TypeError) as exc:
        raise ValueError("月份格式必須為 YYYY-MM") from exc
    if start_date > end_date:
        raise ValueError("start 不可晚於 end")
    current_month = date.today().replace(day=1)
    if end_date > current_month:
        raise ValueError("end 不可晚於本月")
    result = []
    cursor = start_date
    while cursor <= end_date:
        result.append((cursor.year, cursor.month))
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return result


def sync_revenue(database: Database, symbol: str, start: str, end: str) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError("找不到股票代號；請先更新全市場清單")
    months = _iter_months(start, end)
    written = 0
    missing = 0
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers, follow_redirects=True) as client:
        for year, month in months:
            row = fetch_revenue_month(client, symbol, instrument["market"], year, month)
            if row:
                database.upsert_monthly_revenue(row)
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


def analyze_revenue(rows: list[dict]) -> dict:
    if not rows:
        return {}
    latest = rows[-1]
    revenues = [float(row["revenue"]) for row in rows]

    def rolling_yoy(period: int) -> float | None:
        if len(revenues) < period + 12:
            return None
        current = sum(revenues[-period:])
        previous = sum(revenues[-period - 12 : -12])
        return (current / previous - 1) * 100 if previous else None

    consecutive_positive = 0
    for row in reversed(rows):
        if row["yoy_percent"] is not None and row["yoy_percent"] > 0:
            consecutive_positive += 1
        else:
            break
    rank = sum(value <= revenues[-1] for value in revenues) / len(revenues) * 100
    previous_max = max(revenues[:-1]) if len(revenues) > 1 else None
    return {
        "symbol": latest["symbol"],
        "as_of": latest["revenue_month"],
        "revenue_thousands": latest["revenue"],
        "mom_percent": latest["mom_percent"],
        "yoy_percent": latest["yoy_percent"],
        "rolling_3m_yoy_percent": rolling_yoy(3),
        "rolling_6m_yoy_percent": rolling_yoy(6),
        "rolling_12m_yoy_percent": rolling_yoy(12),
        "consecutive_positive_yoy_months": consecutive_positive,
        "historical_percentile": rank,
        "is_record_high": previous_max is not None and revenues[-1] > previous_max,
        "observations": len(rows),
    }
