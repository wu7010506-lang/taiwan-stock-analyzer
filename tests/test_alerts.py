from datetime import date, timedelta
from decimal import Decimal

from app.alerts import (_apply_position_context, _institution_streak,
                        _long_trade_decision, build_alerts)
from app.database import Database
from app.domain import DailyPrice, Instrument


def test_institution_streak_counts_latest_direction():
    rows = [{"foreign_net": value} for value in [1000, -500, 2000, 3000, 4000]]
    assert _institution_streak(rows, "foreign_net") == (3, 9000)


def test_alert_center_monitors_watchlist_technical_signals(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    start = date(2026, 1, 1)
    database.upsert_prices([
        DailyPrice("2330", "TWSE", start + timedelta(days=index), Decimal(100 + index),
                   Decimal(102 + index), Decimal(99 + index), Decimal(101 + index), 10000)
        for index in range(65)
    ])
    database.add_to_watchlist("2330", "TWSE")
    with database.connect() as connection:
        connection.execute("INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent) VALUES(?,?,?,?,?)", ("2330", "TWSE", "2026-06", 1000, 25))
        connection.execute("INSERT INTO institutional_trades(symbol,market,trade_date,foreign_net,trust_net,source) VALUES(?,?,?,?,?,?)", ("2330", "TWSE", "2026-03-06", 100000, 20000, "test"))
    result = build_alerts(database, context={"market_score": 60, "regime": "偏多", "events": []})
    assert result["stocks_monitored"] == 1
    assert any(item["title"] == "RSI 進入偏熱區" for item in result["alerts"])
    assert any(item["title"] == "接近已同步歷史高點" for item in result["alerts"])
    assert result["decisions"][0]["action"] == "短線可買進研究"
    assert result["decisions"][0]["confidence"] in {"中", "高"}
    assert "不是自動交易指令" in result["decisions"][0]["disclaimer"]


def test_long_decision_uses_quality_valuation_and_timing(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "24")])
    recommendation = {"score": 76, "business_quality_score": 80,
        "cashflow_quality_score": 75, "durability_score": 90, "value_score": 68,
        "risk_resilience_score": 72, "invalidation_conditions": [],
        "speculation_risk": "低", "evidence_years": 5, "industry_model": "半導體資本密集模型",
        "trade_date": "2026-07-22"}
    result = _long_trade_decision(database, "2330", "台積電", recommendation)
    assert result["action"] == "長線可分批買進研究"
    assert result["can_buy"] is True
    assert result["mode"] == "long"


def test_long_decision_reports_insufficient_data(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    result = _long_trade_decision(database, "2330", "台積電", None)
    assert result["tone"] == "insufficient"
    assert result["can_buy"] is False


def test_position_stop_loss_overrides_generic_hold():
    decision = {"action": "續抱", "tone": "hold", "can_buy": False,
                "can_sell": False, "mode": "long", "positive_reasons": [],
                "risk_reasons": []}
    stock = {"is_held": True, "average_cost": 100, "shares": 1000,
             "unrealized_return": -.12, "stop_loss": 90, "target_price": 130,
             "stop_triggered": True, "target_reached": False,
             "investment_horizon": "long"}
    result = _apply_position_context(decision, stock)
    assert result["can_sell"] is True
    assert "停損" in result["action"]
