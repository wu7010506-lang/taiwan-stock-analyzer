from __future__ import annotations

import json
from bisect import bisect_right
from statistics import mean, median

from app.database import Database
from app.providers import _parse_date
from app.recommendations import recommend_stocks


TRACKED_FACTORS = (
    "business_quality_score", "cashflow_quality_score", "durability_score",
    "value_score", "risk_resilience_score", "growth_quality_score", "market_score",
    "quality_score", "technical_score", "chip_score", "liquidity_score", "news_score",
)


def capture_recommendation_snapshots(database: Database, context: dict,
                                     profiles: tuple[str, ...] = ("evidence_based", "balanced"),
                                     limit: int = 100) -> dict:
    index_date = context.get("as_of")
    index_close = context.get("index_close")
    if index_date and index_close is not None:
        try:
            normalized_date = _parse_date(str(index_date)).isoformat()
            with database.connect() as connection:
                connection.execute(
                    """INSERT INTO market_index_snapshots
                       (trade_date, close, market_score, regime) VALUES(?,?,?,?)
                       ON CONFLICT(trade_date) DO UPDATE SET close=excluded.close,
                         market_score=excluded.market_score, regime=excluded.regime,
                         fetched_at=CURRENT_TIMESTAMP""",
                    (normalized_date, index_close, context.get("market_score"),
                     context.get("regime")),
                )
        except (TypeError, ValueError):
            pass
    counts = {}
    for profile in profiles:
        rows = recommend_stocks(database, limit=limit,
                                 min_completeness=0 if profile == "evidence_based" else 70,
                                 profile=profile, context=context)
        payload = []
        for rank, row in enumerate(rows, 1):
            if row.get("close") is None or not row.get("trade_date"):
                continue
            factors = {key: row.get(key) for key in TRACKED_FACTORS if row.get(key) is not None}
            decision = row.get("evidence_decision") or row.get("rating")
            payload.append((row["trade_date"], row["symbol"], row["market"], profile,
                row.get("method_version") or "unknown", rank, row["score"], decision,
                row["close"], index_close, context.get("market_score"), context.get("regime"),
                row.get("industry"), row.get("industry_category"),
                json.dumps(factors, ensure_ascii=False),
                json.dumps(row.get("reasons") or [], ensure_ascii=False),
                json.dumps((row.get("invalidation_conditions") or []) +
                           (row.get("risks") or []), ensure_ascii=False)))
        with database.connect() as connection:
            connection.executemany(
                """INSERT INTO recommendation_snapshots
                   (snapshot_date,symbol,market,profile,model_version,rank,score,decision,
                    close,market_close,market_score,market_regime,industry,industry_category,
                    factors_json,reasons_json,risks_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(snapshot_date,symbol,market,profile) DO UPDATE SET
                     model_version=excluded.model_version, rank=excluded.rank,
                     score=excluded.score, decision=excluded.decision, close=excluded.close,
                     market_close=excluded.market_close, market_score=excluded.market_score,
                     market_regime=excluded.market_regime, industry=excluded.industry,
                     industry_category=excluded.industry_category,
                     factors_json=excluded.factors_json, reasons_json=excluded.reasons_json,
                     risks_json=excluded.risks_json, created_at=CURRENT_TIMESTAMP""", payload)
        counts[profile] = len(payload)
    return {"status": "completed", "profiles": counts,
            "total_rows": sum(counts.values())}


def model_performance(database: Database, profile: str = "evidence_based",
                      horizon: int = 20, min_score: float = 65) -> dict:
    with database.connect() as connection:
        snapshots = [dict(row) for row in connection.execute(
            """SELECT s.*, i.name FROM recommendation_snapshots s
               LEFT JOIN instruments i ON i.symbol=s.symbol AND i.market=s.market
               WHERE s.profile=? AND s.score>=?
               ORDER BY s.snapshot_date DESC, s.rank""", (profile, min_score))]
        prices = [dict(row) for row in connection.execute(
            """SELECT symbol,trade_date,close FROM daily_prices ORDER BY symbol,trade_date""")]
        index_rows = [dict(row) for row in connection.execute(
            "SELECT trade_date,close FROM market_index_snapshots ORDER BY trade_date")]
    price_map: dict[str, list[dict]] = {}
    for row in prices:
        price_map.setdefault(row["symbol"], []).append(row)
    index_dates = [row["trade_date"] for row in index_rows]
    outcomes = []
    for snapshot in snapshots:
        rows = price_map.get(snapshot["symbol"], [])
        dates = [row["trade_date"] for row in rows]
        start = bisect_right(dates, snapshot["snapshot_date"])
        target = start + horizon - 1
        stock_return = max_drawdown = benchmark_return = excess_return = None
        if target < len(rows):
            entry = float(snapshot["close"])
            stock_return = (float(rows[target]["close"]) / entry - 1) * 100
            max_drawdown = min((float(row["close"]) / entry - 1) * 100
                               for row in rows[start:target + 1])
            index_start = bisect_right(index_dates, snapshot["snapshot_date"])
            index_target = index_start + horizon - 1
            if snapshot.get("market_close") and index_target < len(index_rows):
                benchmark_return = (float(index_rows[index_target]["close"])
                                    / float(snapshot["market_close"]) - 1) * 100
                excess_return = stock_return - benchmark_return
        outcomes.append({**snapshot, "return_percent": stock_return,
                         "max_drawdown_percent": max_drawdown,
                         "benchmark_return_percent": benchmark_return,
                         "excess_return_percent": excess_return,
                         "matured": stock_return is not None,
                         "factors": json.loads(snapshot.pop("factors_json")),
                         "reasons": json.loads(snapshot.pop("reasons_json")),
                         "risks": json.loads(snapshot.pop("risks_json"))})
    matured = [row for row in outcomes if row["matured"]]
    returns = [row["return_percent"] for row in matured]
    excess = [row["excess_return_percent"] for row in matured
              if row["excess_return_percent"] is not None]
    drawdowns = [row["max_drawdown_percent"] for row in matured]
    return {"profile": profile, "horizon": horizon, "min_score": min_score,
            "total_signals": len(outcomes), "matured_signals": len(matured),
            "pending_signals": len(outcomes) - len(matured),
            "win_rate_percent": (sum(value > 0 for value in returns) / len(returns) * 100
                                 if returns else None),
            "average_return_percent": mean(returns) if returns else None,
            "median_return_percent": median(returns) if returns else None,
            "average_excess_return_percent": mean(excess) if excess else None,
            "average_max_drawdown_percent": mean(drawdowns) if drawdowns else None,
            "outcomes": outcomes[:200]}
