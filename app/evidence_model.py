from __future__ import annotations

from collections import defaultdict
from math import sqrt
from statistics import mean, median

from app.database import Database


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return None if numerator is None or denominator in (None, 0) else numerator / denominator


def _variation(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    center = mean(values)
    if center == 0:
        return None
    return sqrt(sum((value - center) ** 2 for value in values) / len(values)) / abs(center)


def build_evidence_from_rows(rows: list[dict]) -> dict[str, dict]:
    """Build evidence features from a caller-defined, point-in-time row set."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["symbol"]].append(row)

    output = {}
    for symbol, periods in grouped.items():
        by_year: dict[int, list[dict]] = defaultdict(list)
        for row in periods:
            by_year[int(row["fiscal_year"])].append(row)
        annual = []
        for year, quarters in sorted(by_year.items()):
            if len({row["fiscal_quarter"] for row in quarters}) < 4:
                continue
            q4 = next((row for row in quarters if row["fiscal_quarter"] == 4), None)
            if not q4:
                continue
            summary = dict(q4)
            for field in ("revenue", "gross_profit", "operating_income", "net_income", "eps"):
                values = [row[field] for row in quarters if row.get(field) is not None]
                summary[field] = sum(values) if len(values) == 4 else None
            # Cash-flow fields in FinMind are year-to-date; Q4 already is the annual value.
            annual.append(summary)
        years = len({row["fiscal_year"] for row in periods})
        cash_periods = [row for row in periods if row["operating_cash_flow"] is not None]
        fcf_values = [row["free_cash_flow"] for row in periods
                      if row["free_cash_flow"] is not None]
        annual_roe = [value for row in annual
                      if (value := _ratio(row["net_income"], row["equity"])) is not None]
        annual_margin = [value for row in annual
                         if (value := _ratio(row["operating_income"], row["revenue"])) is not None]
        annual_fcf_margin = [value for row in annual
                             if (value := _ratio(row["free_cash_flow"], row["revenue"])) is not None]
        annual_conversion = [value for row in annual
                             if row["net_income"] and row["net_income"] > 0
                             and (value := _ratio(row["operating_cash_flow"], row["net_income"]))
                             is not None]
        annual_revenues = [(row["fiscal_year"], row["revenue"]) for row in annual
                           if row["revenue"] and row["revenue"] > 0]
        revenue_cagr = None
        if len(annual_revenues) >= 3:
            first_year, first = annual_revenues[0]
            last_year, last = annual_revenues[-1]
            span = last_year - first_year
            if span > 0:
                revenue_cagr = (last / first) ** (1 / span) - 1
        latest = periods[-1]
        profitable_annual = [row for row in annual if row["net_income"] is not None]
        positive_eps = [row for row in annual if row["eps"] is not None]
        output[symbol] = {
            "evidence_years": years,
            "evidence_periods": len(periods),
            "cash_flow_periods": len(cash_periods),
            "evidence_ready": years >= 5 and len(cash_periods) >= 12 and len(annual) >= 4,
            "annual_periods": len(annual),
            "median_roe_annual": median(annual_roe) * 100 if annual_roe else None,
            "roe_variation": _variation(annual_roe),
            "median_operating_margin": median(annual_margin) * 100 if annual_margin else None,
            "margin_variation": _variation(annual_margin),
            "median_fcf_margin": median(annual_fcf_margin) * 100 if annual_fcf_margin else None,
            "cash_conversion": median(annual_conversion) if annual_conversion else None,
            "positive_fcf_ratio": (sum(value > 0 for value in fcf_values) / len(fcf_values)
                                   if fcf_values else None),
            "profitable_year_ratio": (sum(row["net_income"] > 0 for row in profitable_annual)
                                      / len(profitable_annual) if profitable_annual else None),
            "positive_eps_year_ratio": (sum(row["eps"] > 0 for row in positive_eps)
                                        / len(positive_eps) if positive_eps else None),
            "revenue_cagr_annual": revenue_cagr * 100 if revenue_cagr is not None else None,
            "latest_debt_ratio": (_ratio(latest["total_liabilities"], latest["total_assets"])
                                  * 100 if _ratio(latest["total_liabilities"],
                                                  latest["total_assets"]) is not None else None),
            "latest_free_cash_flow": latest["free_cash_flow"],
            "latest_annual_operating_margin": (
                _ratio(annual[-1]["operating_income"], annual[-1]["revenue"]) * 100
                if annual and _ratio(annual[-1]["operating_income"], annual[-1]["revenue"])
                is not None else None
            ),
        }
    return output


def build_fundamental_evidence(database: Database) -> dict[str, dict]:
    """Build auditable multi-year features; no missing value is silently scored as good."""
    with database.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT * FROM financial_snapshots
               WHERE statement_date IS NOT NULL
               ORDER BY symbol, fiscal_year, fiscal_quarter"""
        )]
    return build_evidence_from_rows(rows)
