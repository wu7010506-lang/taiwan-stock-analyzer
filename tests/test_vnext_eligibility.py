from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.vnext_eligibility import assess_vnext_data_eligibility
from app.vnext_model import evaluate_vnext_stock, recommend_vnext_stocks


def _database_with_complete_history(
    tmp_path: Path, valuation_date: str = "2026-07-24"
) -> Database:
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "半導體業")])

    prices = []
    current = date(2023, 7, 24)
    while current <= date(2026, 7, 24):
        if current.weekday() < 5:
            prices.append(DailyPrice(
                "2330", "TWSE", current,
                Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), 10_000,
            ))
        current += timedelta(days=1)
    database.upsert_prices(prices)

    for year in range(2021, 2026):
        for quarter in range(1, 5):
            database.upsert_financials({
                "symbol": "2330", "market": "TWSE", "fiscal_year": year,
                "fiscal_quarter": quarter, "report_type": "finmind",
                "revenue": 1000, "gross_profit": 500, "operating_income": 300,
                "net_income": 200, "eps": 2, "total_assets": 10_000,
                "total_liabilities": 2_000, "equity": 8_000,
                "operating_cash_flow": 250 * quarter,
                "capital_expenditure": 50 * quarter, "free_cash_flow": 200 * quarter,
                "statement_date": f"{year}-{quarter * 3:02d}-28", "source": "test",
            })
    database.upsert_financials({
        "symbol": "2330", "market": "TWSE", "fiscal_year": 2026,
        "fiscal_quarter": 1, "report_type": "finmind", "revenue": 1100,
        "gross_profit": 550, "operating_income": 330, "net_income": 220, "eps": 2.2,
        "total_assets": 10_500, "total_liabilities": 2_100, "equity": 8_400,
        "operating_cash_flow": 270, "capital_expenditure": 50, "free_cash_flow": 220,
        "statement_date": "2026-05-15", "source": "test",
    })
    database.upsert_monthly_revenue({
        "symbol": "2330", "market": "TWSE", "revenue_month": "2026-06",
        "revenue": 1000, "previous_month_revenue": 950,
        "previous_year_revenue": 900, "mom_percent": 5.26, "yoy_percent": 11.11,
        "cumulative_revenue": 6000, "previous_year_cumulative_revenue": 5400,
        "cumulative_yoy_percent": 11.11,
    })
    database.upsert_valuation({
        "symbol": "2330", "market": "TWSE", "valuation_date": valuation_date,
        "close_price": 100, "pe_ratio": 18, "pb_ratio": 4,
        "dividend_yield": 2, "dividend_per_share": 4,
        "dividend_year": "2025", "financial_period": "2026Q1",
    })
    database.upsert_institutional_trades([{
        "symbol": "2330", "market": "TWSE", "trade_date": "2026-07-24",
        "foreign_buy": 2000, "foreign_sell": 1000, "foreign_net": 1000,
        "trust_buy": 500, "trust_sell": 300, "trust_net": 200,
        "source": "test",
    }])
    return database


def test_complete_point_in_time_history_is_formally_eligible(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)

    result = assess_vnext_data_eligibility(database, "2330", date(2026, 7, 25))

    assert result["status"] == "eligible"
    assert result["missing"] == []
    assert result["checks"]["financial_history"]["passed"] is True
    assert result["checks"]["price_history"]["passed"] is True
    assert result["checks"]["freshness"]["passed"] is True


def test_compact_valuation_date_is_accepted_as_fresh_data(tmp_path: Path):
    database = _database_with_complete_history(tmp_path, valuation_date="20260724")

    result = assess_vnext_data_eligibility(database, "2330", date(2026, 7, 25))

    assert result["status"] == "eligible"
    assert result["checks"]["freshness"]["valuation_days"] == 1


def test_vnext_handles_a_fresh_valuation_row_without_pe(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)
    database.upsert_valuation({
        "symbol": "2330", "market": "TWSE", "valuation_date": "2026-07-24",
        "close_price": 100, "pe_ratio": None, "pb_ratio": 4,
        "dividend_yield": 2, "dividend_per_share": 4,
        "dividend_year": "2025", "financial_period": "2026Q1",
    })

    result = evaluate_vnext_stock(database, "2330", date(2026, 7, 25), context={})

    assert result["value_score"] is not None
    assert result["valuation_score"] is not None


def test_stock_without_history_is_data_insufficient_not_scored(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("9999", "資料不足公司", "TWSE", "其他")])

    result = assess_vnext_data_eligibility(database, "9999", date(2026, 7, 25))

    assert result["status"] == "insufficient_data"
    assert result["formal_recommendation_allowed"] is False
    assert result["missing"] == ["financial_history", "price_history", "freshness"]


def test_eligibility_never_uses_data_published_after_scoring_date(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)

    result = assess_vnext_data_eligibility(database, "2330", date(2025, 7, 25))

    assert result["status"] == "observation"
    assert result["formal_recommendation_allowed"] is False
    assert result["checks"]["price_history"]["passed"] is False
    assert result["checks"]["freshness"]["valuation_days"] is None
    assert result["checks"]["freshness"]["institution_days"] is None
    assert result["checks"]["point_in_time"]["passed"] is True
    assert result["checks"]["point_in_time"]["ignored_future_rows"] > 0


def test_eligibility_does_not_use_a_quarter_before_conservative_publication_lag(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "A", "TWSE", None)])
    database.upsert_financials({
        "symbol": "2330", "market": "TWSE", "fiscal_year": 2026,
        "fiscal_quarter": 2, "report_type": "test", "revenue": 100,
        "operating_cash_flow": 20, "free_cash_flow": 10,
        "statement_date": "2026-06-30", "source": "test",
    })

    result = assess_vnext_data_eligibility(database, "2330", date(2026, 7, 20))

    assert result["checks"]["financial_history"]["cash_flow_periods"] == 0
    assert result["checks"]["point_in_time"]["ignored_future_rows"] == 1


def test_vnext_separates_company_value_action_and_confidence(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)
    for year in range(2021, 2026):
        for quarter in range(1, 5):
            database.upsert_financials({
                "symbol": "2330", "market": "TWSE", "fiscal_year": year,
                "fiscal_quarter": quarter, "report_type": "finmind",
                "revenue": 1000 + (year - 2021) * 80, "gross_profit": 550,
                "operating_income": 350, "net_income": 220, "eps": 2.2,
                "total_assets": 2500, "total_liabilities": 500, "equity": 2000,
                "operating_cash_flow": 300 * quarter,
                "capital_expenditure": 60 * quarter, "free_cash_flow": 240 * quarter,
                "statement_date": f"{year}-{quarter * 3:02d}-28", "source": "test",
            })

    result = evaluate_vnext_stock(
        database,
        "2330",
        date(2026, 7, 25),
        context={"market_score": 65, "overheat_score": 20, "regime": "bull_normal"},
    )

    assert result["model"] == "vnext"
    assert result["value_score"] >= 70
    assert result["action"] in {"buy", "accumulate"}
    assert result["confidence"] in {"medium", "high"}
    assert result["company_quality"]["cashflow_quality"] >= 70
    assert result["supporting_reasons"]
    assert result["risks"] is not None


def test_vnext_recommendations_apply_position_and_market_cash_limits(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)

    result = recommend_vnext_stocks(
        database,
        date(2026, 7, 25),
        context={"market_score": 65, "overheat_score": 20, "regime": "bull_normal"},
        limit=10,
    )

    assert result["model"] == "vnext"
    assert result["cash_target_percent"] == 20
    assert result["universe_summary"] == {
        "evaluated": 1, "eligible": 1, "observation": 0, "insufficient_data": 0,
    }
    assert result["recommendations"][0]["rank"] == 1
    assert 0 < result["recommendations"][0]["suggested_position_percent"] <= 10
    assert result["sector_limits_percent"] == 25


def test_vnext_flags_institution_driven_price_surge_as_crowding(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)
    closes = [100, 105, 110, 118, 125]
    days = [date(2026, 7, 20) + timedelta(days=index) for index in range(5)]
    database.upsert_prices([
        DailyPrice("2330", "TWSE", day, Decimal(str(close)), Decimal(str(close + 1)),
                   Decimal(str(close - 1)), Decimal(str(close)), 10_000)
        for day, close in zip(days, closes)
    ])
    database.upsert_institutional_trades([{
        "symbol": "2330", "market": "TWSE", "trade_date": day.isoformat(),
        "foreign_buy": 6000, "foreign_sell": 1000, "foreign_net": 5000,
        "trust_buy": 1000, "trust_sell": 500, "trust_net": 500, "source": "test",
    } for day in days])

    result = evaluate_vnext_stock(
        database,
        "2330",
        date(2026, 7, 25),
        context={"market_score": 65, "overheat_score": 20, "regime": "bull_normal"},
    )

    assert result["crowding_risk"] == "high"
    assert "institution_driven_surge" in result["risks"]
    assert result["action"] != "buy"


def test_vnext_suspends_recommendation_for_verified_material_negative_event(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)
    context = {
        "market_score": 65, "overheat_score": 20, "regime": "bull_normal",
        "events": [{
            "symbol": "2330", "verified": True, "materiality": "high",
            "sentiment": -20, "event_type": "governance", "title": "重大治理事件",
        }],
    }

    result = evaluate_vnext_stock(database, "2330", date(2026, 7, 25), context=context)

    assert result["recommendation_suspended"] is True
    assert result["action"] == "wait"
    assert "verified_material_negative_event" in result["risks"]
    assert result["value_score"] is not None


def test_suspended_stock_is_excluded_from_vnext_recommendation_positions(tmp_path: Path):
    database = _database_with_complete_history(tmp_path)
    context = {
        "market_score": 65, "overheat_score": 20, "regime": "bull_normal",
        "events": [{
            "symbol": "2330", "verified": True, "materiality": "high",
            "sentiment": -20, "event_type": "governance", "title": "重大治理事件",
        }],
    }

    result = recommend_vnext_stocks(database, date(2026, 7, 25), context, limit=10)

    assert result["recommendations"] == []


def test_empty_vnext_list_explains_which_data_is_missing(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("9999", "資料不足公司", "TWSE", "其他")])

    result = recommend_vnext_stocks(database, date(2026, 7, 25), {}, limit=10)

    assert result["recommendations"] == []
    assert result["universe_summary"]["insufficient_data"] == 1
    assert result["missing_summary"] == {
        "financial_history": 1, "price_history": 1, "freshness": 1,
    }
