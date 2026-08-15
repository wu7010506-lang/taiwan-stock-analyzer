from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.database import Database
from app.domain import DailyPrice, Instrument
from app.short_term_positions import (
    ManualShortTermPositionOpen,
    ShortTermPositionExecution,
    ShortTermPositionOpen,
    evaluate_short_term_position,
    open_manual_short_term_position,
    open_short_term_position,
    record_short_term_execution,
    short_term_position_summary,
)
from app.short_term_trade import cost_adjusted_break_even_price


def _position(**overrides):
    row = {
        "remaining_shares": 1000,
        "active_stop": 95,
        "target_price": 110,
        "target_reduction_executed": 0,
    }
    row.update(overrides)
    return row


def _prices(closes):
    return [
        {"trade_date": f"2026-08-{index + 1:02d}", "close": close}
        for index, close in enumerate(closes)
    ]


def test_target_recommends_selling_half_only_once():
    decision = evaluate_short_term_position(
        _position(), _prices([100, 111]), "2026-08-02"
    )
    assert decision["action"] == "reduce_next_open"
    assert decision["suggested_shares"] == 500

    after_reduction = evaluate_short_term_position(
        _position(remaining_shares=500, target_reduction_executed=1),
        _prices([100, 111, 112]),
        "2026-08-03",
    )
    assert after_reduction["action"] == "hold"


def test_stop_and_tenth_session_take_priority_over_target():
    stopped = evaluate_short_term_position(
        _position(active_stop=112), _prices([100, 113, 111]), "2026-08-03"
    )
    assert stopped["action"] == "exit_next_open"
    assert "停損" in stopped["reason"]

    timed_out = evaluate_short_term_position(
        _position(), _prices([100] * 9 + [115]), "2026-08-10"
    )
    assert timed_out["action"] == "exit_next_open"
    assert "10 個交易日" in timed_out["reason"]


def test_stale_quote_suppresses_sell_advice():
    decision = evaluate_short_term_position(
        _position(active_stop=105), _prices([100]), "2026-08-02"
    )
    assert decision["action"] == "data_pending"


def _database_with_position(tmp_path):
    database = Database(tmp_path / "positions.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "半導體業")])
    start = date(2026, 8, 3)
    database.upsert_prices([
        DailyPrice(
            "2330",
            "TWSE",
            start + timedelta(days=index),
            Decimal(100),
            Decimal(113),
            Decimal(99),
            Decimal(str(close)),
            10000,
        )
        for index, close in enumerate([100, 111])
    ])
    payload = ShortTermPositionOpen(
        symbol="2330",
        market="TWSE",
        signal_date=date(2026, 8, 2),
        strategy_version="short-term-v1",
        entry_date=start,
        entry_price=100,
        shares=1000,
        stop_price=95,
        target_price=110,
    )
    open_short_term_position(database, payload)
    return database, payload


def test_position_persists_and_duplicate_open_is_rejected(tmp_path):
    database, payload = _database_with_position(tmp_path)
    summary = short_term_position_summary(database, date(2026, 8, 4))
    assert summary["active_count"] == 1
    assert summary["action_count"] == 1
    assert summary["positions"][0]["decision"]["action"] == "reduce_next_open"
    assert summary["positions"][0]["events"][0]["event_type"] == "open"
    with pytest.raises(ValueError, match="已有進行中的"):
        open_short_term_position(database, payload)


def test_confirmed_half_sale_raises_stop_to_cost_adjusted_break_even(tmp_path):
    database, _ = _database_with_position(tmp_path)
    result = record_short_term_execution(
        database,
        "2330",
        ShortTermPositionExecution(
            action="reduce",
            execution_date=date(2026, 8, 5),
            execution_price=111,
            shares=500,
        ),
    )
    assert result["remaining_shares"] == 500
    assert result["active_stop"] == cost_adjusted_break_even_price(100)
    assert result["target_reduction_executed"] is True

    summary = short_term_position_summary(database, date(2026, 8, 5))
    position = summary["positions"][0]
    assert position["decision"]["action"] == "hold"
    assert position["events"][0]["event_type"] == "target_reduce"


def test_confirmed_full_exit_closes_position(tmp_path):
    database, _ = _database_with_position(tmp_path)
    result = record_short_term_execution(
        database,
        "2330",
        ShortTermPositionExecution(
            action="exit",
            execution_date=date(2026, 8, 5),
            execution_price=94,
            shares=1000,
            reason="short_term_stop_loss",
        ),
    )
    assert result["status"] == "closed"
    assert short_term_position_summary(database, date(2026, 8, 5))["active_count"] == 0


def test_individual_analysis_can_open_any_instrument_without_ranking_signal(tmp_path):
    database = Database(tmp_path / "manual-position.db")
    database.initialize()
    database.upsert_instruments([Instrument("3029", "零壹", "TWSE", "資訊服務業")])
    database.upsert_prices([
        DailyPrice(
            "3029", "TWSE", date(2026, 8, 14), Decimal(100), Decimal(103),
            Decimal(98), Decimal(101), 20000,
        )
    ])
    result = open_manual_short_term_position(
        database,
        ManualShortTermPositionOpen(
            symbol="3029",
            entry_date=date(2026, 8, 14),
            entry_price=100,
            shares=2000,
            stop_price=95,
            target_price=110,
        ),
    )
    assert result["status"] == "open"
    position = short_term_position_summary(database, date(2026, 8, 14))["positions"][0]
    assert position["source"] == "individual_analysis"
    assert position["strategy_version"] == "manual-individual-analysis-v1"
    assert position["events"][0]["reason"] == "individual_analysis_purchase"
