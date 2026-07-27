from __future__ import annotations

from datetime import date, datetime, timedelta

from app.database import Database
from app.dividends import sync_dividends
from app.financials import sync_financials
from app.institutions import sync_institutional_trades
from app.ownership import sync_ownership
from app.revenue import sync_revenue
from app.service import sync_history
from app.valuation import sync_valuations


DATASETS = ("prices", "revenues", "valuations", "financials", "dividends", "ownership", "institutions")


def _age_days(value: str | None, compact: bool = False) -> int | None:
    if not value:
        return None
    text = str(value).replace("/", "-")
    if compact and len(text) >= 8 and "-" not in text:
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 7:
        text += "-01"
    try:
        return (date.today() - date.fromisoformat(text[:10])).days
    except ValueError:
        return None


def analysis_sync_plan(database: Database, symbol: str) -> dict:
    if not database.get_instrument(symbol):
        raise LookupError(f"找不到股票 {symbol}")
    with database.connect() as connection:
        specs = {
            "prices": ("daily_prices", "trade_date"),
            "revenues": ("monthly_revenues", "revenue_month"),
            "valuations": ("valuations", "valuation_date"),
            "financials": ("financial_snapshots", "statement_date"),
            "dividends": ("dividend_events", "ex_date"),
            "ownership": ("shareholder_distribution", "data_date"),
            "institutions": ("institutional_trades", "trade_date"),
        }
        coverage = {}
        for name, (table, column) in specs.items():
            row = connection.execute(
                f"SELECT COUNT(*) AS rows, MIN({column}) AS first_date, MAX({column}) AS latest_date, MAX(fetched_at) AS last_fetched_at FROM {table} WHERE symbol=?",
                (symbol,),
            ).fetchone()
            coverage[name] = dict(row)
        attempts = {row["dataset"]: dict(row) for row in connection.execute(
            "SELECT * FROM analysis_sync_state WHERE symbol=?", (symbol,))}
        market_latest_date = connection.execute(
            "SELECT MAX(trade_date) AS trade_date FROM daily_prices WHERE close > 0"
        ).fetchone()["trade_date"]
    ages = {name: _age_days(item["latest_date"], name == "valuations")
            for name, item in coverage.items()}
    fetched_ages = {name: _age_days(item["last_fetched_at"]) for name, item in coverage.items()}
    ready = {
        "prices": coverage["prices"]["rows"] >= 120 and (
            bool(coverage["prices"]["latest_date"] and market_latest_date
                 and coverage["prices"]["latest_date"] >= market_latest_date)
            or _successful_today(attempts.get("prices"))
        ),
        "revenues": coverage["revenues"]["rows"] >= 10 and ages["revenues"] is not None and ages["revenues"] <= 75,
        "valuations": coverage["valuations"]["rows"] >= 10 and ages["valuations"] is not None and ages["valuations"] <= 7,
        "financials": coverage["financials"]["rows"] >= 1 and (
            ages["financials"] is not None and ages["financials"] <= 180
            or fetched_ages["financials"] is not None and fetched_ages["financials"] <= 7
        ),
        # A successful recent attempt counts for datasets that can legitimately return zero rows.
        "dividends": bool(coverage["dividends"]["rows"]) or _recent_success(attempts.get("dividends"), 30),
        "ownership": ages["ownership"] is not None and ages["ownership"] <= 14 or _recent_success(attempts.get("ownership"), 7),
        "institutions": ages["institutions"] is not None and ages["institutions"] <= 7,
    }
    missing = [name for name in DATASETS if not ready[name]]
    return {"symbol": symbol, "ready": not missing, "missing": missing,
            "market_latest_date": market_latest_date,
            "coverage": {name: {**coverage[name], "age_days": ages[name],
                                  "fetched_age_days": fetched_ages[name], "ready": ready[name]}
                         for name in DATASETS}}


def _recent_success(row: dict | None, days: int) -> bool:
    if not row or row.get("status") != "completed":
        return False
    try:
        attempted = datetime.fromisoformat(str(row["last_attempt"]))
    except ValueError:
        return False
    return datetime.now() - attempted <= timedelta(days=days)


def _successful_today(row: dict | None) -> bool:
    if not row or row.get("status") != "completed":
        return False
    try:
        return datetime.fromisoformat(str(row["last_attempt"])).date() == date.today()
    except ValueError:
        return False


def _record(database: Database, symbol: str, dataset: str, status: str,
            error: str | None = None) -> None:
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO analysis_sync_state(symbol,dataset,last_attempt,status,error)
               VALUES(?,?,CURRENT_TIMESTAMP,?,?) ON CONFLICT(symbol,dataset) DO UPDATE SET
               last_attempt=CURRENT_TIMESTAMP,status=excluded.status,error=excluded.error""",
            (symbol, dataset, status, error),
        )


def _incomplete_coverage_reason(dataset: str, coverage: dict) -> str:
    """Explain a no-exception sync that still did not meet its readiness rule."""
    return (f"{dataset} sync returned without an exception but coverage remains insufficient "
            f"(rows={coverage.get('rows') or 0}, latest_date={coverage.get('latest_date') or 'none'})")


def sync_missing_analysis_data(database: Database, symbol: str, force: bool = False) -> dict:
    plan = analysis_sync_plan(database, symbol)
    requested = list(DATASETS if force else plan["missing"])
    today = date.today()
    start = today - timedelta(days=365)
    # A stock with sufficient history only needs the current month refreshed.
    # This also bypasses lag in TWSE's bulk STOCK_DAY_ALL endpoint cheaply.
    price_start = (today.replace(day=1)
                   if plan["coverage"]["prices"]["rows"] >= 120 else start)
    operations = {
        "prices": lambda: sync_history(database, symbol, price_start, today),
        "revenues": lambda: sync_revenue(database, symbol, start.strftime("%Y-%m"), today.strftime("%Y-%m")),
        "valuations": lambda: sync_valuations(database, symbol, start.strftime("%Y-%m"), today.strftime("%Y-%m")),
        "financials": lambda: sync_financials(database, symbol),
        "dividends": lambda: sync_dividends(database, symbol),
        "ownership": lambda: sync_ownership(database, symbol),
        "institutions": lambda: sync_institutional_trades(database, symbol),
    }
    results = {}
    for name in requested:
        try:
            results[name] = operations[name]()
            _record(database, symbol, name, "completed")
        except Exception as exc:
            results[name] = {"status": "failed", "error": str(exc)}
            _record(database, symbol, name, "failed", str(exc)[:500])
    after = analysis_sync_plan(database, symbol)
    for name in after["missing"]:
        detail = results.get(name)
        if isinstance(detail, dict) and detail.get("status") == "failed":
            continue
        reason = _incomplete_coverage_reason(name, after["coverage"][name])
        if isinstance(detail, dict):
            results[name] = {**detail, "status": "incomplete", "error": reason}
        else:
            results[name] = {"status": "incomplete", "error": reason}
        _record(database, symbol, name, "incomplete", reason)
    return {"symbol": symbol, "status": "completed" if not after["missing"] else "partial",
            "requested": requested, "results": results, "remaining": after["missing"],
            "coverage": after["coverage"]}


def sync_watchlist_analysis_data(database: Database) -> dict:
    rows = database.list_watchlist()
    results = []
    for row in rows:
        result = sync_missing_analysis_data(database, row["symbol"])
        errors = {
            dataset: detail.get("error")
            for dataset, detail in result["results"].items()
            if isinstance(detail, dict) and detail.get("status") in {"failed", "incomplete"}
        }
        results.append({"symbol": row["symbol"], "status": result["status"],
                        "requested": result["requested"], "remaining": result["remaining"],
                        "errors": errors})
    completed = sum(item["status"] == "completed" for item in results)
    failures = [item for item in results if item["status"] != "completed"]
    return {"status": "completed" if completed == len(results) else "partial",
            "stocks": len(results), "completed": completed,
            "partial": len(results) - completed, "results": results,
            "failures": failures}
