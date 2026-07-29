"""Shared, conservative availability rules for research-time data cuts.

The database stores period-end dates for several feeds.  A period end is not
the date an investor could have seen the value, so models and backtests must
use these expressions rather than filtering only on the source period date.
"""

FINANCIAL_Q1_Q3_LAG_DAYS = 45
FINANCIAL_Q4_LAG_DAYS = 90
REVENUE_PUBLICATION_LAG_DAYS = 10


def financial_available_sql(column: str = "statement_date") -> str:
    return (
        f"CASE WHEN fiscal_quarter=4 THEN date({column}, '+{FINANCIAL_Q4_LAG_DAYS} days') "
        f"ELSE date({column}, '+{FINANCIAL_Q1_Q3_LAG_DAYS} days') END"
    )


def revenue_available_sql(column: str = "revenue_month") -> str:
    # Monthly revenue is represented as YYYY-MM.  Treat it as available ten
    # calendar days after the next month starts, a conservative MOPS proxy.
    return f"date({column} || '-01', '+1 month', '+{REVENUE_PUBLICATION_LAG_DAYS} days')"


POINT_IN_TIME_POLICY = {
    "financial_q1_q3_lag_days": FINANCIAL_Q1_Q3_LAG_DAYS,
    "financial_q4_lag_days": FINANCIAL_Q4_LAG_DAYS,
    "revenue_publication_lag_days": REVENUE_PUBLICATION_LAG_DAYS,
    "price_cutoff": "signal-day close; simulated entry is the following available session",
    "institution_cutoff": "same trade date only after close; use prior session for pre-close signals",
    "limitation": "Availability is a conservative proxy until source-level announcement timestamps are stored.",
}
