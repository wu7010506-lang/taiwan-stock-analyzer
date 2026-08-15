from __future__ import annotations

from datetime import date

from app.database import Database
from app.financial_integrity import assess_financial_integrity
from app.point_in_time import financial_available_sql, next_session_available_sql, revenue_available_sql


def normalized_date_sql(column: str) -> str:
    """Normalize ISO and compact YYYYMMDD dates held by legacy providers."""
    return (
        f"CASE WHEN length({column})=8 AND {column} NOT GLOB '*[^0-9]*' "
        f"THEN substr({column},1,4)||'-'||substr({column},5,2)||'-'||substr({column},7,2) "
        f"ELSE {column} END"
    )


def _days_old(as_of_date: date, value: str | None) -> int | None:
    if not value:
        return None
    return (as_of_date - date.fromisoformat(value)).days


def _latest_revenue_month_due(as_of_date: date) -> str:
    """Return the newest monthly-revenue period required on this date.

    Listed companies report the preceding month's revenue by the 10th.  Before
    that deadline, requiring the immediately preceding month would mark every
    otherwise-current stock stale for several calendar days.
    """
    months_back = 2 if as_of_date.day <= 10 else 1
    year = as_of_date.year
    month = as_of_date.month - months_back
    while month <= 0:
        year -= 1
        month += 12
    return f"{year:04d}-{month:02d}"


def assess_vnext_data_eligibility(
    database: Database,
    symbol: str,
    as_of_date: date,
) -> dict:
    """Decide whether point-in-time data can support a formal vNext recommendation."""
    cutoff = as_of_date.isoformat()
    valuation_date = normalized_date_sql("valuation_date")
    valuation_available_date = next_session_available_sql(valuation_date)
    financial_available_date = financial_available_sql("statement_date")
    revenue_available_date = revenue_available_sql("revenue_month")
    institution_available_date = next_session_available_sql("trade_date")
    with database.connect() as connection:
        financial = dict(connection.execute(
            f"""SELECT COUNT(*) AS periods,
                      COUNT(DISTINCT fiscal_year) AS years,
                      SUM(CASE WHEN operating_cash_flow IS NOT NULL
                               AND free_cash_flow IS NOT NULL THEN 1 ELSE 0 END)
                        AS cash_flow_periods,
                      SUM(CASE WHEN statement_date IS NULL THEN 1 ELSE 0 END)
                        AS missing_statement_dates,
                      MAX(statement_date) AS latest_date
               FROM financial_snapshots
               WHERE symbol=? AND statement_date IS NOT NULL
                 AND {financial_available_date}<=?""",
            (symbol, cutoff),
        ).fetchone())
        financial_rows = [dict(row) for row in connection.execute(
            f"""SELECT fiscal_year, fiscal_quarter, total_assets, total_liabilities, equity
                FROM financial_snapshots
                WHERE symbol=? AND statement_date IS NOT NULL
                  AND {financial_available_date}<=?
                ORDER BY fiscal_year, fiscal_quarter""",
            (symbol, cutoff),
        )]
        complete_years = connection.execute(
            f"""SELECT COUNT(*) FROM (
                   SELECT fiscal_year
                   FROM financial_snapshots
                   WHERE symbol=? AND statement_date IS NOT NULL
                     AND {financial_available_date}<=?
                   GROUP BY fiscal_year
                   HAVING COUNT(DISTINCT fiscal_quarter)=4
               )""",
            (symbol, cutoff),
        ).fetchone()[0]
        price = dict(connection.execute(
            """SELECT COUNT(*) AS periods, MIN(trade_date) AS first_date,
                      MAX(trade_date) AS latest_date
               FROM daily_prices WHERE symbol=? AND trade_date<=?""",
            (symbol, cutoff),
        ).fetchone())
        latest_revenue = connection.execute(
            f"""SELECT MAX(revenue_month) FROM monthly_revenues
               WHERE symbol=? AND {revenue_available_date}<=?""",
            (symbol, cutoff),
        ).fetchone()[0]
        latest_valuation = connection.execute(
            f"""SELECT MAX({valuation_date}) FROM valuations
               WHERE symbol=? AND {valuation_available_date}<=?""",
            (symbol, cutoff),
        ).fetchone()[0]
        latest_institution = connection.execute(
            f"""SELECT MAX(trade_date) FROM institutional_trades
               WHERE symbol=? AND {institution_available_date}<=?""",
            (symbol, cutoff),
        ).fetchone()[0]
        ignored_future_rows = connection.execute(
            f"""SELECT
                 (SELECT COUNT(*) FROM financial_snapshots
                 WHERE symbol=? AND statement_date IS NOT NULL
                   AND {financial_available_date}>?)
               + (SELECT COUNT(*) FROM daily_prices
                  WHERE symbol=? AND trade_date>?)
               + (SELECT COUNT(*) FROM monthly_revenues
                 WHERE symbol=? AND {revenue_available_date}>?)
               + (SELECT COUNT(*) FROM valuations
                  WHERE symbol=? AND {valuation_available_date}>?)
               + (SELECT COUNT(*) FROM institutional_trades
                  WHERE symbol=? AND {institution_available_date}>?)""",
            (symbol, cutoff, symbol, cutoff, symbol, cutoff,
             symbol, cutoff, symbol, cutoff),
        ).fetchone()[0]

    price_span_days = None
    if price["first_date"] and price["latest_date"]:
        price_span_days = (
            date.fromisoformat(price["latest_date"]) - date.fromisoformat(price["first_date"])
        ).days
    financial_passed = bool(
        complete_years >= 5
        and (financial["cash_flow_periods"] or 0) >= 12
        and (financial["missing_statement_dates"] or 0) == 0
    )
    price_passed = bool((price_span_days or 0) >= 1095 and (price["periods"] or 0) >= 600)

    revenue_date = f"{latest_revenue}-01" if latest_revenue else None
    ages = {
        "price_days": _days_old(as_of_date, price["latest_date"]),
        "financial_days": _days_old(as_of_date, financial["latest_date"]),
        "revenue_days": _days_old(as_of_date, revenue_date),
        "valuation_days": _days_old(as_of_date, latest_valuation),
        "institution_days": _days_old(as_of_date, latest_institution),
    }
    revenue_due_month = _latest_revenue_month_due(as_of_date)
    revenue_timely = bool(latest_revenue and latest_revenue >= revenue_due_month)
    freshness_passed = bool(
        ages["price_days"] is not None and ages["price_days"] <= 7
        and ages["financial_days"] is not None and ages["financial_days"] <= 190
        and revenue_timely
        and ages["valuation_days"] is not None and ages["valuation_days"] <= 14
        and ages["institution_days"] is not None and ages["institution_days"] <= 7
    )

    integrity_issues = assess_financial_integrity(financial_rows)
    checks = {
        "financial_history": {
            "passed": financial_passed,
            "complete_years": complete_years,
            "cash_flow_periods": financial["cash_flow_periods"] or 0,
        },
        "price_history": {
            "passed": price_passed,
            "periods": price["periods"] or 0,
            "span_days": price_span_days,
        },
        "freshness": {
            "passed": freshness_passed, **ages,
            "revenue_due_month": revenue_due_month,
            "latest_revenue_month": latest_revenue,
        },
        "point_in_time": {
            "passed": True,
            "ignored_future_rows": ignored_future_rows,
        },
        "financial_integrity": {
            "passed": not integrity_issues,
            "issues": integrity_issues,
        },
    }
    missing = [name for name, check in checks.items() if not check["passed"]]
    formal_recommendation_allowed = not missing
    has_core_history = bool((financial["periods"] or 0) or (price["periods"] or 0))
    if formal_recommendation_allowed:
        status = "eligible"
    elif has_core_history:
        status = "observation"
    else:
        status = "insufficient_data"
    return {
        "symbol": symbol,
        "as_of_date": cutoff,
        "status": status,
        "formal_recommendation_allowed": formal_recommendation_allowed,
        "missing": missing,
        "checks": checks,
    }
