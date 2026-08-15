from app.short_term_trade import (
    build_breakout_trade_plan,
    required_rr_for_market,
    taiwan_stock_tick_size,
)


def _prices():
    rows = []
    for index in range(60):
        close = 100 + index * 0.1
        rows.append({"trade_date": f"2026-01-{(index % 28) + 1:02d}", "open": close - .2,
                     "high": close + .4, "low": close - .5, "close": close, "volume": 1000})
    rows[-1].update({"open": 107, "high": 112, "low": 106, "close": 110, "volume": 2000})
    return rows


def _indicators():
    return {"atr_14": 2, "breakout_level_20d": 106, "trend_confirmation": True,
            "volume_ratio_20": 2, "rsi_14": 55, "mfi_14": 60, "natr_14": 2}


def test_breakout_plan_uses_independent_atr_target_instead_of_reverse_rr_target():
    plan = build_breakout_trade_plan(_prices(), _indicators(), "range")

    assert plan["stop"] == 107.0  # Max of breakout-candle low (106) and close - 1.5 ATR (107).
    assert plan["reference_entry"] == 110.0
    assert plan["maximum_entry_price"] == 110.5
    assert plan["maximum_entry_formula"] == "參考進場價 + 0.25 × ATR14"
    assert plan["maximum_entry_parameters"]["atr_14"] == 2.0
    assert plan["risk_per_share"] == 3.0
    assert plan["required_rr"] == 2.0
    assert plan["minimum_target_required_rr"] == 116.0
    assert plan["math_verification"]["rr_1_5_target"] == 114.5
    assert plan["math_verification"]["rr_2_target"] == 116.0
    assert plan["math_verification"]["rr_3_target"] == 119.0
    assert plan["mfi_check"] == {"value": 60.0, "hot_threshold": 80, "result": "未偏熱"}
    assert plan["natr_check"] == {"value_percent": 2.0, "high_threshold_percent": 7, "result": "未過高"}
    assert plan["trigger_checks"]["breakout"]["passed"] is True
    assert plan["trigger_checks"]["volume"]["required_ratio"] == 1.3
    assert plan["trigger_checks"]["risk_reward"]["provisional"] is False
    assert plan["requires_next_open_recheck"] is True
    assert plan["execution_costs"]["assumed_round_trip_rate_percent"] == 0.785
    assert plan["cost_adjusted_risk_reward_at_next_resistance"] is None
    assert plan["planned_target"] == 114.0
    assert plan["planned_target_independent_from_rr"] is True
    assert plan["cost_adjusted_risk_reward"] == 0.81
    assert "未使用 RR 反推" in plan["planned_target_basis"]
    assert plan["status"] == "不建議執行"
    assert plan["minimum_target_required_rr_after_cost"] > plan["minimum_target_required_rr"]


def test_insufficient_reward_is_a_hard_breaker_not_a_soft_warning():
    prices = _prices()
    prices[10]["high"] = 115  # A real structural ceiling exists before the required 3R target.
    plan = build_breakout_trade_plan(prices, _indicators(), "defensive")

    assert plan["status"] == "不建議執行"
    assert any("風險報酬比不足" in reason for reason in plan["blocking_reasons"])


def test_market_rr_thresholds_are_fixed_and_explicit():
    assert required_rr_for_market("trend") == 1.5
    assert required_rr_for_market("range") == 2.0
    assert required_rr_for_market("defensive") == 3.0


def test_taiwan_stock_tick_schedule_is_applied_to_reference_prices():
    assert taiwan_stock_tick_size(9.99) == 0.01
    assert taiwan_stock_tick_size(10) == 0.05
    assert taiwan_stock_tick_size(50) == 0.1
    assert taiwan_stock_tick_size(100) == 0.5
    assert taiwan_stock_tick_size(500) == 1.0
    assert taiwan_stock_tick_size(1000) == 5.0

    indicators = _indicators() | {"atr_14": 2.3}
    plan = build_breakout_trade_plan(_prices(), indicators, "range")
    assert plan["maximum_entry_price_raw"] == 110.575
    assert plan["maximum_entry_price"] == 110.5
    assert plan["price_tick_policy"]


def test_near_limit_up_signal_requires_next_open_confirmation():
    indicators = _indicators() | {"return_1d_percent": 9.5}
    plan = build_breakout_trade_plan(_prices(), indicators, "range")

    assert any("接近漲停" in reason for reason in plan["blocking_reasons"])
    assert plan["trigger_checks"]["market_access"]["passed"] is False


def test_multi_signal_overextension_blocks_chasing_a_confirmed_breakout():
    prices = _prices()
    prices[-1].update({"open": 27.8, "high": 29.0, "low": 27.5, "close": 28.65,
                       "volume": 4_378_500})
    indicators = {
        "atr_14": 1.267,
        "breakout_level_20d": 27.5,
        "trend_confirmation": True,
        "volume_ratio_20": 4.3785,
        "rsi_14": 74.1264,
        "mfi_14": 76.3134,
        "natr_14": 4.4224,
        "return_1d_percent": 4.1818,
        "return_5d_percent": 31.422,
        "sma_5": 25.26,
        "sma_20": 23.3375,
        "bollinger_upper": 27.5727,
    }

    plan = build_breakout_trade_plan(prices, indicators, "trend")

    assert plan["analysis_status"] == "PASS"
    assert plan["trigger_checks"]["chase_control"]["passed"] is False
    assert plan["overextension_check"]["return_5d_percent"] == 31.422
    assert plan["overextension_check"]["distance_to_sma20_percent"] > 20
    assert plan["status"] == "不建議執行"
    assert any("短線漲幅與乖離過度延伸" in reason for reason in plan["blocking_reasons"])
