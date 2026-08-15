from app.database import Database
from app.domain import Instrument
from app.market_context import _normalize_event
from app.recommendations import (
    PROFILE_WEIGHTS,
    _evidence_exclusion_reasons,
    _percentile,
    recommend_stocks,
)
from app.financial_integrity import assess_financial_integrity


def test_percentile_supports_inverse_ranking():
    assert _percentile(30, [10, 20, 30]) == 1
    assert _percentile(10, [10, 20, 30], inverse=True) == 1


def test_evidence_model_excludes_high_debt_and_negative_latest_free_cash_flow():
    assert _evidence_exclusion_reasons({
        "latest_debt_ratio": 77.65, "latest_free_cash_flow": -183_436_000,
    }) == ["latest_debt_ratio_above_70", "latest_free_cash_flow_negative"]


def test_financial_integrity_rejects_consistent_balance_sheet_unit_scale_break():
    assert assess_financial_integrity([
        {"fiscal_year": 2025, "fiscal_quarter": 4, "total_assets": 100_000,
         "total_liabilities": 70_000, "equity": 30_000},
        {"fiscal_year": 2026, "fiscal_quarter": 1, "total_assets": 100,
         "total_liabilities": 70, "equity": 30},
    ]) == ["financial_unit_scale_anomaly"]


def test_research_weight_profiles_total_one_hundred_percent():
    assert all(sum(weights.values()) == 100 for weights in PROFILE_WEIGHTS.values())
    assert PROFILE_WEIGHTS["balanced"] == {
        "quality": 25, "value": 20, "technical": 15, "revenue_growth": 15,
        "chip": 8, "liquidity": 7, "market": 7, "news": 3,
    }
    assert PROFILE_WEIGHTS["long_term_quality"] == {
        "quality": 30, "durability": 15, "value": 15, "scale": 20,
        "revenue_growth": 5, "technical": 3, "liquidity": 7,
        "market": 3, "chip": 1, "news": 1,
    }
    assert PROFILE_WEIGHTS["evidence_based"] == {
        "business_quality": 30, "cashflow_quality": 20, "durability": 15,
        "value": 15, "risk_resilience": 10, "growth_quality": 5, "market_fit": 5,
    }


def test_recommendations_require_sufficient_data(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "半導體業")])
    assert recommend_stocks(database) == []
    assert recommend_stocks(database, profile="value") == []


def test_recommendations_combine_market_technical_flow_and_events(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "半導體業")])
    with database.connect() as connection:
        for day, close in enumerate((90, 94, 97, 99, 105), 1):
            connection.execute(
                "INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume,turnover) VALUES(?,?,?,?,?,?,?,?,?)",
                ("2330", "TWSE", f"2026-07-{day:02d}", close, close, close, close, 1000, 1_000_000),
            )
        for index in range(24):
            year, month_index = divmod(6 + index, 12)
            revenue_month = f"{2024 + year}-{month_index + 1:02d}"
            connection.execute("INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent,cumulative_yoy_percent) VALUES(?,?,?,?,?,?)", ("2330", "TWSE", revenue_month, 80 if index < 12 else 100, 25, 25))
        connection.execute("INSERT INTO valuations(symbol,market,valuation_date,close_price,pe_ratio,pb_ratio,dividend_yield) VALUES(?,?,?,?,?,?,?)", ("2330", "TWSE", "2026-07-05", 105, 12, 1.8, 3))
        connection.execute("INSERT INTO financial_snapshots(symbol,market,fiscal_year,fiscal_quarter,report_type,revenue,gross_profit,net_income,eps,total_assets,total_liabilities,equity) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("2330", "TWSE", 2026, 1, "general", 1000, 500, 200, 5, 2000, 500, 1500))
        connection.execute("INSERT INTO institutional_trades(symbol,market,trade_date,foreign_net,trust_net,source) VALUES(?,?,?,?,?,?)", ("2330", "TWSE", "2026-07-05", 100000, 20000, "test"))
    context = {"available": True, "market_score": 70, "regime": "偏多", "as_of": "1150705",
               "events": [{"symbol": "2330", "title": "取得重要訂單", "sentiment": 14}]}

    result = recommend_stocks(database, min_completeness=70, context=context)[0]

    assert result["method_version"] == "long-term-quality-v8"
    assert result["market_score"] == 70
    assert result["news_score"] == 64
    assert result["annual_growth_score"] == 50
    assert result["annual_revenue_yoy"] == 25
    assert result["revenue_growth_score"] == 50
    assert result["technical_score"] > 50
    assert result["event_count"] == 1
    assert result["institution_influence"] in {"中", "高"}
    assert result["speculation_risk"] in {"中", "高"}
    assert result["institution_net_ratio_5d"] is not None

    long_term = recommend_stocks(database, min_completeness=70,
                                 profile="long_term_quality", context=context)[0]
    assert long_term["durability_score"] == 50
    assert long_term["financial_history_periods"] == 1
    assert long_term["durability_coverage"] < 50


def test_official_event_keywords_are_small_bounded_adjustments():
    event = _normalize_event({"公司代號": "2330", "主旨 ": "取得訂單並增加投資"}, "TWSE")
    assert event["symbol"] == "2330"
    assert event["sentiment"] == 20
