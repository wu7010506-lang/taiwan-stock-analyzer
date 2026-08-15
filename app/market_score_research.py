"""Point-in-time validation of the fixed daily market-score rule.

This module deliberately evaluates the existing 40/55 cut-offs.  It does not
search for alternative cut-offs or modify the live market-context rule.
"""
from __future__ import annotations

from statistics import mean, median

from app.database import Database
from app.market_context import _analyze_index


BUCKETS = (("risk_off", "偏弱 (<40)"), ("range", "盤整 (40–54.9)"),
           ("trend", "偏強 (>=55)"))
HORIZONS = (3, 5, 10)
MIN_HISTORY = 120


def _bucket(score: float) -> str:
    if score < 40:
        return "risk_off"
    if score >= 55:
        return "trend"
    return "range"


def _forward_drawdown(closes: list[float]) -> float:
    """Worst close-to-close drawdown from the signal close during a horizon."""
    entry = closes[0]
    return min((close / entry - 1) * 100 for close in closes)


def _summary(rows: list[dict]) -> dict:
    if not rows:
        return {"samples": 0, "average_return_percent": None,
                "median_return_percent": None, "win_rate_percent": None,
                "worst_return_percent": None, "average_worst_drawdown_percent": None,
                "worst_drawdown_percent": None}
    returns = [row["forward_return_percent"] for row in rows]
    drawdowns = [row["worst_drawdown_percent"] for row in rows]
    return {"samples": len(rows), "average_return_percent": round(mean(returns), 4),
            "median_return_percent": round(median(returns), 4),
            "win_rate_percent": round(sum(value > 0 for value in returns) / len(returns) * 100, 2),
            "worst_return_percent": round(min(returns), 4),
            "average_worst_drawdown_percent": round(mean(drawdowns), 4),
            "worst_drawdown_percent": round(min(drawdowns), 4)}


def validate_market_score(database: Database, *, start_date: str | None = None,
                          end_date: str | None = None) -> dict:
    """Test whether frozen score states separate subsequent TAIEX outcomes."""
    with database.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT trade_date, close FROM market_index_snapshots ORDER BY trade_date"
        )]
    closes = [float(row["close"]) for row in rows]
    observations: dict[int, list[dict]] = {horizon: [] for horizon in HORIZONS}
    for index in range(MIN_HISTORY - 1, len(rows)):
        signal_date = rows[index]["trade_date"]
        if start_date and signal_date < start_date:
            continue
        if end_date and signal_date > end_date:
            continue
        context = _analyze_index(closes[:index + 1])
        score = float(context["market_score"])
        for horizon in HORIZONS:
            if index + horizon >= len(rows):
                continue
            future = closes[index:index + horizon + 1]
            observations[horizon].append({
                "signal_date": signal_date, "score": round(score, 4),
                "bucket": _bucket(score),
                "forward_return_percent": (future[-1] / future[0] - 1) * 100,
                "worst_drawdown_percent": _forward_drawdown(future),
            })

    results = []
    for horizon in HORIZONS:
        samples = observations[horizon]
        by_bucket = []
        for key, label in BUCKETS:
            by_bucket.append({"bucket": key, "label": label,
                              **_summary([row for row in samples if row["bucket"] == key])})
        results.append({"horizon_sessions": horizon, "total_samples": len(samples),
                        "all_market": _summary(samples), "by_market_state": by_bucket})
    return {
        "mode": "market_score_validation", "version": "market-score-v1-frozen-40-55",
        "score_rule": "Existing market score reconstructed from only signal-date-and-earlier TAIEX closes.",
        "thresholds": {"risk_off_below": 40, "trend_at_least": 55},
        "start_date": start_date, "end_date": end_date, "minimum_history_sessions": MIN_HISTORY,
        "results": results, "formal_recommendation_allowed": False,
        "limitations": [
            "This tests association with subsequent TAIEX close returns, not causality or an executable trading strategy.",
            "Future return horizons overlap; their rows are descriptive and not independent observations.",
            "It does not validate individual-stock selection, transaction costs, breadth, or intraday execution.",
            "Thresholds are frozen from the live rule; do not optimise them using these results.",
        ],
    }
