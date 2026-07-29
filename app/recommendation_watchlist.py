from __future__ import annotations

from app.database import Database


def add_top_recommendations_to_watchlist(
    database: Database, result: dict | list[dict], limit: int = 20
) -> dict:
    """Add the leading formal recommendations without altering existing entries."""
    added = 0
    considered = 0
    rows = result if isinstance(result, list) else (result.get("recommendations") or [])
    for row in rows[:limit]:
        symbol = row.get("symbol")
        market = row.get("market")
        if not symbol or not market:
            continue
        considered += 1
        already_watched = database.is_watched(symbol)
        database.add_to_watchlist(symbol, market)
        if not already_watched:
            added += 1
    return {"considered": considered, "added": added, "limit": limit}
