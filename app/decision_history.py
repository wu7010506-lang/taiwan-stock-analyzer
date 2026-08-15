from __future__ import annotations

import json
from datetime import date

from app.dashboard import build_daily_dashboard
from app.database import Database


def capture_daily_decision_history(database: Database, market_context: dict,
                                   quality_snapshot_id: int | None = None,
                                   as_of_date: date | None = None) -> dict:
    """Persist the user-visible decision state with references to its evidence."""
    as_of_date = as_of_date or date.today()
    dashboard = build_daily_dashboard(database, market_context, as_of_date)
    vnext = database.get_latest_vnext_recommendation_run()
    database.save_daily_decision_log(
        as_of_date.isoformat(), json.dumps(market_context, ensure_ascii=False, default=str),
        json.dumps(dashboard, ensure_ascii=False, default=str), quality_snapshot_id,
        vnext["snapshot_date"] if vnext else None,
    )
    return {"status": "completed", "decision_date": as_of_date.isoformat(),
            "quality_snapshot_id": quality_snapshot_id,
            "vnext_snapshot_date": vnext["snapshot_date"] if vnext else None}
