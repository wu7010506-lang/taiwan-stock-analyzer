from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from app.config import settings
from app.database import Database


TDCC_URL = "https://openapi.tdcc.com.tw/v1/opendata/1-5"
LEVEL_LABELS = {
    1: "1–999 股", 2: "1–5 張", 3: "5–10 張", 4: "10–15 張",
    5: "15–20 張", 6: "20–30 張", 7: "30–40 張", 8: "40–50 張",
    9: "50–100 張", 10: "100–200 張", 11: "200–400 張",
    12: "400–600 張", 13: "600–800 張", 14: "800–1,000 張",
    15: "1,000 張以上",
}
_cache: tuple[datetime, list[dict]] | None = None


def _number(value: object, integer: bool = False) -> int | float | None:
    text = str(value or "").replace(",", "").replace("%", "").strip()
    if not text:
        return None
    try:
        number = Decimal(text)
        return int(number) if integer else float(number)
    except InvalidOperation:
        return None


def _date_value(row: dict) -> str:
    value = next((value for key, value in row.items() if key.lstrip("\ufeff") == "資料日期"), "")
    text = str(value).strip()
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 else text


def normalize_tdcc_row(row: dict) -> dict:
    return {
        "symbol": str(row.get("證券代號", "")).strip(),
        "data_date": _date_value(row),
        "holding_level": _number(row.get("持股分級"), integer=True),
        "holders": _number(row.get("人數"), integer=True),
        "shares": _number(row.get("股數"), integer=True),
        "percentage": _number(row.get("占集保庫存數比例%")),
        "source": "TDCC 股權分散表",
    }


def _fetch_tdcc_rows() -> list[dict]:
    global _cache
    now = datetime.now()
    if _cache and now - _cache[0] < timedelta(hours=6):
        return _cache[1]
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=max(settings.http_timeout_seconds, 45), headers=headers, follow_redirects=True) as client:
        response = client.get(TDCC_URL)
        response.raise_for_status()
        rows = response.json()
    _cache = (now, rows)
    return rows


def sync_ownership(database: Database, symbol: str) -> dict:
    if not database.get_instrument(symbol):
        raise LookupError("找不到股票，請先同步上市、上櫃清單。")
    rows = [normalize_tdcc_row(row) for row in _fetch_tdcc_rows()
            if str(row.get("證券代號", "")).strip() == symbol]
    rows = [row for row in rows if row["data_date"] and row["holding_level"] is not None]
    if not rows:
        raise LookupError("集保結算所目前沒有這檔股票的股權分散資料。")
    return {"symbol": symbol, "rows_written": database.upsert_shareholder_distribution(rows),
            "data_date": rows[0]["data_date"], "status": "completed"}


def analyze_ownership(rows: list[dict]) -> dict | None:
    brackets = [row for row in rows if row["holding_level"] in LEVEL_LABELS]
    if not brackets:
        return None

    def aggregate(first: int, last: int) -> dict:
        selected = [row for row in brackets if first <= row["holding_level"] <= last]
        return {
            "holders": sum(row.get("holders") or 0 for row in selected),
            "shares": sum(row.get("shares") or 0 for row in selected),
            "percentage": round(sum(row.get("percentage") or 0 for row in selected), 4),
        }

    small, medium, large = aggregate(1, 5), aggregate(6, 10), aggregate(11, 15)
    gap = large["percentage"] - small["percentage"]
    label = "持股較集中" if gap >= 15 else "小額持股較分散" if gap <= -15 else "結構相對均衡"
    return {
        "symbol": brackets[0]["symbol"], "as_of": brackets[0]["data_date"],
        "total_holders": sum(row.get("holders") or 0 for row in brackets),
        "small": small, "medium": medium, "large": large,
        "concentration_label": label,
        "brackets": [{**row, "label": LEVEL_LABELS[row["holding_level"]]} for row in brackets],
        "disclaimer": "持股級距只能作為散戶與大戶的代理指標；大額帳戶不等於投信，也可能是大股東、其他法人或保管帳戶。",
    }
