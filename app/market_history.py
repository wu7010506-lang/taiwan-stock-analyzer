from __future__ import annotations

from datetime import date

import httpx

from app.database import Database
from app.providers import _parse_date


TWSE_INDEX_MONTH_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"


def sync_market_index_history(database: Database, start: date, end: date) -> dict:
    """Store official TAIEX closes for reproducible historical strategy tests."""
    if start > end:
        raise ValueError("start date must not be after end date")
    months = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current)
        current = current.replace(
            year=current.year + (current.month == 12), month=current.month % 12 + 1
        )
    rows: list[tuple[str, float]] = []
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for month in months:
            response = client.get(TWSE_INDEX_MONTH_URL, params={
                "date": month.strftime("%Y%m%d"), "response": "json",
            })
            response.raise_for_status()
            for values in response.json().get("data", []):
                if len(values) < 5:
                    continue
                try:
                    trade_date = _parse_date(str(values[0]))
                    close = float(str(values[4]).replace(",", ""))
                except (TypeError, ValueError):
                    continue
                if start <= trade_date <= end:
                    rows.append((trade_date.isoformat(), close))
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO market_index_snapshots(trade_date, close)
               VALUES(?, ?)
               ON CONFLICT(trade_date) DO UPDATE SET close=excluded.close,
                 fetched_at=CURRENT_TIMESTAMP""",
            rows,
        )
    return {"status": "completed", "start": start.isoformat(), "end": end.isoformat(),
            "months": len(months), "rows_written": len(rows)}
