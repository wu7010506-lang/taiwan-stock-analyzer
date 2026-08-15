from pathlib import Path

from app.database import Database
from app.domain import Instrument
from app.historical_fundamentals import normalize_finmind_dividends, normalize_finmind_history
from app.evidence_model import build_fundamental_evidence


def item(date, kind, value):
    return {"date": date, "type": kind, "value": value}


def test_normalizes_finmind_history_and_calculates_fcf():
    rows = normalize_finmind_history(
        "2330", "TWSE",
        [item("2025-06-30", "Revenue", 1000), item("2025-06-30", "EPS", 10)],
        [item("2025-06-30", "TotalAssets", 5000),
         item("2025-06-30", "CashAndCashEquivalents", 800)],
        [item("2025-06-30", "CashFlowsFromOperatingActivities", 300),
         item("2025-06-30", "PropertyAndPlantAndEquipment", -120)],
    )
    assert rows[0]["fiscal_quarter"] == 2
    assert rows[0]["capital_expenditure"] == 120
    assert rows[0]["free_cash_flow"] == 180
    assert rows[0]["cash_and_equivalents"] == 800


def test_dividend_and_database_coverage(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "TWSE", "TSMC", None)])
    for year in range(2021, 2026):
        database.upsert_financials({"symbol": "2330", "market": "TWSE",
            "fiscal_year": year, "fiscal_quarter": 4, "report_type": "finmind",
            "operating_cash_flow": 100, "capital_expenditure": 40,
            "free_cash_flow": 60, "statement_date": f"{year}-12-31",
            "source": "FinMind / MOPS"})
    dividends = normalize_finmind_dividends("2330", "TWSE", [{
        "CashExDividendTradingDate": "2025-06-12",
        "CashEarningsDistribution": 5, "CashStatutorySurplus": 0,
        "StockEarningsDistribution": 0, "StockStatutorySurplus": 0,
    }])
    database.upsert_dividend_events(dividends)
    coverage = database.get_fundamentals_coverage("2330")
    assert coverage["financial_years"] == 5
    assert coverage["cash_flow_periods"] == 5
    assert coverage["dividend_events"] == 1


def test_evidence_requires_multi_year_cash_flow(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "TWSE", "TSMC", None)])
    for year in range(2021, 2026):
        for quarter in range(1, 5):
            database.upsert_financials({
                "symbol": "2330", "market": "TWSE", "fiscal_year": year,
                "fiscal_quarter": quarter, "report_type": "finmind",
                "revenue": 1000, "operating_income": 300,
                "net_income": 200, "eps": 2,
                "total_assets": 10000, "total_liabilities": 2000, "equity": 8000,
                "operating_cash_flow": 250 * quarter, "capital_expenditure": 50 * quarter,
                "free_cash_flow": 200 * quarter,
                "statement_date": f"{year}-{quarter * 3:02d}-28", "source": "test",
            })
    evidence = build_fundamental_evidence(database)["2330"]
    assert evidence["evidence_ready"] is True
    assert evidence["positive_fcf_ratio"] == 1
    assert evidence["revenue_cagr_annual"] == 0
    assert evidence["median_fcf_margin"] == 20
