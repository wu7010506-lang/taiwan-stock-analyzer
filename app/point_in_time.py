"""Shared, conservative availability rules for research-time data cuts.

The database stores period-end dates for several feeds.  A period end is not
the date an investor could have seen the value, so models and backtests must
use these expressions rather than filtering only on the source period date.
"""

FINANCIAL_Q1_Q3_LAG_DAYS = 45
FINANCIAL_Q4_LAG_DAYS = 90
REVENUE_PUBLICATION_LAG_DAYS = 10
VALUATION_PUBLICATION_LAG_DAYS = 1
INSTITUTION_PUBLICATION_LAG_DAYS = 1


def financial_available_sql(column: str = "statement_date") -> str:
    fallback = (
        f"CASE WHEN fiscal_quarter=4 THEN date({column}, '+{FINANCIAL_Q4_LAG_DAYS} days') "
        f"ELSE date({column}, '+{FINANCIAL_Q1_Q3_LAG_DAYS} days') END"
    )
    return (
        "CASE WHEN published_date IS NOT NULL THEN date(published_date) "
        "WHEN source LIKE '%official OpenAPI%' AND fetched_at IS NOT NULL "
        f"THEN MIN(date(fetched_at), {fallback}) ELSE {fallback} END"
    )


def revenue_available_sql(column: str = "revenue_month") -> str:
    # Monthly revenue is represented as YYYY-MM.  Treat it as available ten
    # calendar days after the next month starts, a conservative MOPS proxy.
    return f"date({column} || '-01', '+1 month', '+{REVENUE_PUBLICATION_LAG_DAYS} days')"


def next_session_available_sql(column: str) -> str:
    """Conservative proxy for end-of-day feeds with no publication timestamp."""
    return f"date({column}, '+1 day')"


POINT_IN_TIME_POLICY = {
    "financial_q1_q3_lag_days": FINANCIAL_Q1_Q3_LAG_DAYS,
    "financial_q4_lag_days": FINANCIAL_Q4_LAG_DAYS,
    "revenue_publication_lag_days": REVENUE_PUBLICATION_LAG_DAYS,
    "valuation_publication_lag_days": VALUATION_PUBLICATION_LAG_DAYS,
    "institution_publication_lag_days": INSTITUTION_PUBLICATION_LAG_DAYS,
    "price_cutoff": "signal-day close; simulated entry is the following available session",
    "valuation_and_institution_cutoff": "end-of-day feeds become usable from the next calendar day",
    "limitation": "Verified filing dates are preferred. Official OpenAPI extract dates are not treated as disclosure dates; a locally observed fetch date can only shorten the conservative lag from the day the row was actually obtained, never before it.",
}
