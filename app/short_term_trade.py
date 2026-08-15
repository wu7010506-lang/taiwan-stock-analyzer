"""Frozen, explainable 3–10 session breakout trade-plan rules.

This module deliberately evaluates one strategy only.  It produces research
levels and hard blockers; it never places an order or claims a forecast.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

COMMISSION_RATE_EACH_SIDE = 0.001425
TRANSACTION_TAX_RATE_SELL = 0.003
SLIPPAGE_RATE_EACH_SIDE = 0.001


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def taiwan_stock_tick_size(price: float) -> float:
    """Return the standard TWSE/TPEx cash-equity tick for a positive price."""
    if price < 10:
        return 0.01
    if price < 50:
        return 0.05
    if price < 100:
        return 0.1
    if price < 500:
        return 0.5
    if price < 1000:
        return 1.0
    return 5.0


def _legal_price(price: float, direction: str) -> float:
    """Round a reference level conservatively to a legal Taiwan stock tick."""
    tick = Decimal(str(taiwan_stock_tick_size(price)))
    rounding = ROUND_CEILING if direction == "up" else ROUND_FLOOR
    units = (Decimal(str(price)) / tick).to_integral_value(rounding=rounding)
    return float(units * tick)


def cost_adjusted_break_even_price(entry_price: float) -> float:
    """Return the minimum legal sell price that covers assumed round-trip costs."""
    buy_cost_rate = COMMISSION_RATE_EACH_SIDE + SLIPPAGE_RATE_EACH_SIDE
    sell_cost_rate = (
        COMMISSION_RATE_EACH_SIDE + TRANSACTION_TAX_RATE_SELL + SLIPPAGE_RATE_EACH_SIDE
    )
    raw_price = entry_price * (1 + buy_cost_rate) / (1 - sell_cost_rate)
    return _legal_price(raw_price, "up")


def required_rr_for_market(market_mode: str | None) -> float:
    """Pre-registered thresholds: do not tune them from current results."""
    return {"trend": 1.5, "range": 2.0, "defensive": 3.0}.get(market_mode or "range", 2.0)


def required_volume_ratio_for_market(market_mode: str | None) -> float:
    """Keep breakout volume confirmation hard; weak markets demand more proof."""
    return {"trend": 1.2, "range": 1.3, "defensive": 1.5}.get(market_mode or "range", 1.3)


def build_breakout_trade_plan(prices: list[dict], indicators: dict,
                              market_mode: str | None = "range",
                              average_turnover_20: float | None = None) -> dict:
    """Create a same-horizon breakout plan from daily OHLCV only.

    Entry is the signal close for planning.  The next open must be rechecked
    against ``maximum_entry_price`` so a gap cannot silently invalidate RR.
    """
    rows = [row for row in prices if all(row.get(key) is not None for key in ("open", "high", "low", "close"))]
    unavailable = {"strategy_type": "breakout", "status": "insufficient_data",
                   "blocking_reasons": ["至少需要 60 筆完整日 OHLCV 才能建立突破計畫。"]}
    if len(rows) < 60:
        return unavailable
    close = float(rows[-1]["close"])
    atr = _number(indicators.get("atr_14"))
    breakout_level = _number(indicators.get("breakout_level_20d"))
    if atr is None or atr <= 0 or breakout_level is None:
        return {**unavailable, "blocking_reasons": ["缺少 ATR 或 20 日突破位，不能猜測進場與停損。"]}

    latest_low = float(rows[-1]["low"])
    reference_entry = close
    maximum_entry_raw = close + 0.25 * atr
    maximum_entry = _legal_price(maximum_entry_raw, "down")
    # The stop is anchored to the breakout candle.  1.5 ATR is an upper bound
    # on initial risk for this short holding horizon, not a replacement for it.
    structure_stop = latest_low
    atr_stop = reference_entry - 1.5 * atr
    stop_raw = max(structure_stop, atr_stop)
    stop = _legal_price(stop_raw, "up")
    risk = round(reference_entry - stop, 4) if reference_entry > stop else None
    prior55 = rows[-56:-1]
    next_resistance = (max(float(row["high"]) for row in prior55)
                       if len(prior55) >= 55 else None)
    if next_resistance is not None and next_resistance <= reference_entry:
        next_resistance = None
    minimum_target_1_5r = (_legal_price(reference_entry + 1.5 * risk, "up")
                            if risk else None)
    required_rr = required_rr_for_market(market_mode)
    minimum_target_required_rr = (_legal_price(reference_entry + required_rr * risk, "up")
                                  if risk else None)
    reward_at_resistance = (round(next_resistance - reference_entry, 4)
                            if next_resistance is not None else None)
    rr_at_resistance = (round(reward_at_resistance / risk, 2)
                        if risk and reward_at_resistance is not None and reward_at_resistance > 0 else None)

    # Conservative standard-rate assumptions for a 3–10 day Taiwan cash-equity
    # round trip. Broker discounts vary, so the UI exposes every parameter.
    commission_rate = COMMISSION_RATE_EACH_SIDE
    transaction_tax_rate = TRANSACTION_TAX_RATE_SELL
    slippage_rate_each_side = SLIPPAGE_RATE_EACH_SIDE
    buy_cost_rate = commission_rate + slippage_rate_each_side
    sell_cost_rate = commission_rate + transaction_tax_rate + slippage_rate_each_side
    buy_cash_out = reference_entry * (1 + buy_cost_rate)
    stop_cash_in = stop * (1 - sell_cost_rate)
    net_risk = round(buy_cash_out - stop_cash_in, 4) if risk else None
    minimum_target_after_cost = (_legal_price((buy_cash_out + required_rr * net_risk) /
                                              (1 - sell_cost_rate), "up")
                                 if net_risk else None)
    # The expected target must be independent from the RR hurdle.  Otherwise
    # deriving a target from required RR and then checking RR is a tautology.
    volatility_extension_target = _legal_price(reference_entry + 2 * atr, "down")
    planned_target = (next_resistance if next_resistance is not None
                      else volatility_extension_target)
    planned_target_basis = ("下一個 55 日結構壓力" if next_resistance is not None
                            else "無更高 55 日結構壓力，採固定 2 ATR 波動延伸；未使用 RR 反推")
    net_reward_at_resistance = (round(next_resistance * (1 - sell_cost_rate) - buy_cash_out, 4)
                                if next_resistance is not None else None)
    net_reward_at_planned_target = (round(planned_target * (1 - sell_cost_rate) - buy_cash_out, 4)
                                    if planned_target is not None else None)
    cost_adjusted_rr_at_resistance = (round(net_reward_at_resistance / net_risk, 2)
                                      if net_risk and net_reward_at_resistance is not None
                                      and net_reward_at_resistance > 0 else None)
    cost_adjusted_rr = (round(net_reward_at_planned_target / net_risk, 2)
                        if net_risk and net_reward_at_planned_target is not None
                        and net_reward_at_planned_target > 0 else None)

    volume_ratio = _number(indicators.get("volume_ratio_20"))
    rsi, mfi, natr = (_number(indicators.get(key)) for key in ("rsi_14", "mfi_14", "natr_14"))
    return_5d = _number(indicators.get("return_5d_percent"))
    sma_5 = _number(indicators.get("sma_5"))
    sma_20 = _number(indicators.get("sma_20"))
    bollinger_upper = _number(indicators.get("bollinger_upper"))
    distance_to_sma5 = (close / sma_5 - 1) * 100 if sma_5 else None
    distance_to_sma20 = (close / sma_20 - 1) * 100 if sma_20 else None
    overextension_signals = []
    if distance_to_sma5 is not None and distance_to_sma5 >= 10:
        overextension_signals.append("收盤高於 MA5 至少 10%")
    if distance_to_sma20 is not None and distance_to_sma20 >= 15:
        overextension_signals.append("收盤高於 MA20 至少 15%")
    if bollinger_upper is not None and close > bollinger_upper:
        overextension_signals.append("收盤突破布林上軌")
    if rsi is not None and rsi >= 70:
        overextension_signals.append("RSI 至少 70")
    overextended = bool(
        return_5d is not None
        and return_5d >= 20
        and len(overextension_signals) >= 2
    )
    breakout_pass = close > breakout_level
    trend_pass = bool(indicators.get("trend_confirmation"))
    volume_required = required_volume_ratio_for_market(market_mode)
    volume_pass = volume_ratio is not None and volume_ratio >= volume_required
    atr_risk_pass = risk is not None and risk <= 1.5 * atr + 1e-9
    core_blockers = []
    if not breakout_pass:
        core_blockers.append("收盤尚未突破 20 日高點。")
    if not trend_pass:
        core_blockers.append("日線趨勢未符合收盤價、SMA20、SMA60 多頭排列。")
    if not volume_pass:
        core_blockers.append(f"成交量未達 20 日均量的 {volume_required:g} 倍。")
    if not atr_risk_pass:
        core_blockers.append("突破 K 棒低點無法形成有效短線失效價。")
    soft_risks = []
    if rsi is not None and rsi >= 70:
        soft_risks.append("RSI 偏熱")
    if mfi is not None and mfi >= 80:
        soft_risks.append("MFI 偏熱")
    if natr is not None and natr >= 7:
        soft_risks.append("NATR 過高")
    gap_percent = _number(indicators.get("latest_gap_percent"))
    return_1d = _number(indicators.get("return_1d_percent"))
    if gap_percent is not None and abs(gap_percent) >= 3:
        soft_risks.append("近期跳空幅度偏大")
    if return_1d is not None and abs(return_1d) >= 9:
        soft_risks.append("接近台股單日漲跌幅限制，次日成交風險較高")
    if overextended:
        soft_risks.append("短線漲幅與乖離過度延伸")
    rr_pass = cost_adjusted_rr is not None and cost_adjusted_rr >= required_rr
    near_limit_up = return_1d is not None and return_1d >= 9
    execution_blockers = list(core_blockers)
    if not rr_pass:
        execution_blockers.append(f"本交易不建議執行，原因為成本後風險報酬比不足（市場最低要求 1：{required_rr:g}）。")
    if near_limit_up:
        execution_blockers.append("訊號日接近漲停，次日可能無法以計畫價格成交；須等待實際開盤價重新確認。")
    if overextended:
        execution_blockers.append(
            "短線漲幅與乖離過度延伸，不建議在突破後立即追價；"
            "等待回檔守住突破區或橫盤整理後重新計算。"
        )

    analysis_status = "PASS" if not core_blockers else "NOT_READY"
    status = "條件通過，開盤前仍須重算" if not execution_blockers else "不建議執行"
    return {
        "strategy_type": "breakout", "horizon_sessions": "3-10", "status": status,
        "entry_condition": f"日收盤突破 20 日高點，且成交量至少為 20 日均量 {volume_required:g} 倍；下一日開盤不得高於最高允許進場價。",
        "breakout_level": round(breakout_level, 4), "reference_entry": round(reference_entry, 4),
        "maximum_entry_price": maximum_entry,
        "maximum_entry_price_raw": round(maximum_entry_raw, 4),
        "maximum_entry_formula": "參考進場價 + 0.25 × ATR14",
        "maximum_entry_parameters": {"reference_entry": round(reference_entry, 4), "atr_14": round(atr, 4), "chase_atr_multiple": 0.25},
        "requires_next_open_recheck": True,
        "stop": stop, "stop_price_raw": round(stop_raw, 4),
        "stop_basis": "突破 K 棒低點；若風險超過 1.5 ATR，改用參考進場價 − 1.5 ATR，並向上取至合法跳動單位。",
        "stop_candidates": {"breakout_candle_low": round(structure_stop, 4), "atr_1_5_stop": round(atr_stop, 4), "selected_stop": stop,
                            "selection": "較高者，確保初始風險不超過 1.5 ATR"},
        "risk_per_share": risk, "next_structural_resistance": round(next_resistance, 4) if next_resistance is not None else None,
        "minimum_target_1_5r": minimum_target_1_5r,
        "minimum_target_required_rr": minimum_target_required_rr,
        "minimum_target_required_rr_after_cost": minimum_target_after_cost,
        "planned_target": planned_target,
        "planned_target_basis": planned_target_basis,
        "planned_target_independent_from_rr": True,
        "volatility_extension_target_2atr": volatility_extension_target,
        "risk_reward_at_next_resistance": rr_at_resistance,
        "cost_adjusted_risk_reward_at_next_resistance": cost_adjusted_rr_at_resistance,
        "cost_adjusted_risk_reward": cost_adjusted_rr,
        "required_rr": required_rr,
        "volume_check": {"value": round(volume_ratio, 4) if volume_ratio is not None else None,
                         "required": volume_required, "result": "通過" if volume_ratio is not None and volume_ratio >= volume_required else "未通過"},
        "trigger_checks": {
            "breakout": {
                "label": "收盤突破 20 日高點", "passed": breakout_pass,
                "actual": round(close, 4), "required_above": round(breakout_level, 4),
                "gap_percent": round(max(0, breakout_level / close - 1) * 100, 4) if close else None,
            },
            "trend": {
                "label": "日線趨勢多頭排列", "passed": trend_pass,
                "requirement": "收盤價、SMA20、SMA60 符合固定多頭排列",
            },
            "volume": {
                "label": "成交量確認", "passed": volume_pass,
                "actual_ratio": round(volume_ratio, 4) if volume_ratio is not None else None,
                "required_ratio": volume_required,
                "gap_percent": (round(max(0, volume_required / volume_ratio - 1) * 100, 4)
                                if volume_ratio is not None and volume_ratio > 0 else None),
            },
            "atr_risk": {
                "label": "ATR 停損可執行", "passed": atr_risk_pass,
                "risk_per_share": risk, "maximum_atr_multiple": 1.5,
                "actual_atr_multiple": round(risk / atr, 4) if risk is not None else None,
            },
            "risk_reward": {
                "label": "成本後風險報酬比", "passed": rr_pass,
                "actual": cost_adjusted_rr, "required": required_rr,
                "provisional": bool(core_blockers),
            },
            "market_access": {
                "label": "次日成交可行性", "passed": not near_limit_up,
                "requirement": "訊號日漲幅低於 9%；次日仍須用實際開盤價重算",
            },
            "chase_control": {
                "label": "短線追價風險控制",
                "passed": not overextended,
                "requirement": "5 日漲幅達 20% 時，不得同時出現至少兩項過度延伸訊號",
            },
        },
        "analysis_status": analysis_status, "core_blocking_reasons": core_blockers,
        "soft_risks": soft_risks, "soft_risk_score": len(soft_risks),
        "mfi_check": {"value": round(mfi, 4) if mfi is not None else None, "hot_threshold": 80,
                      "result": "偏熱" if mfi is not None and mfi >= 80 else "未偏熱" if mfi is not None else "資料不足"},
        "natr_check": {"value_percent": round(natr, 4) if natr is not None else None, "high_threshold_percent": 7,
                       "result": "過高" if natr is not None and natr >= 7 else "未過高" if natr is not None else "資料不足"},
        "overextension_check": {
            "passed": not overextended,
            "return_5d_percent": round(return_5d, 4) if return_5d is not None else None,
            "return_5d_threshold_percent": 20,
            "distance_to_sma5_percent": round(distance_to_sma5, 4) if distance_to_sma5 is not None else None,
            "distance_to_sma5_threshold_percent": 10,
            "distance_to_sma20_percent": round(distance_to_sma20, 4) if distance_to_sma20 is not None else None,
            "distance_to_sma20_threshold_percent": 15,
            "close": round(close, 4),
            "bollinger_upper": round(bollinger_upper, 4) if bollinger_upper is not None else None,
            "rsi_14": round(rsi, 4) if rsi is not None else None,
            "confirmation_signals": overextension_signals,
            "rule": "5 日漲幅至少 20%，且 MA5／MA20 乖離、布林上軌、RSI 中至少兩項過熱時，禁止隔日追價。",
        },
        "math_verification": {"risk": risk,
                                "rr_1_5_target": minimum_target_1_5r,
                                "rr_2_target": _legal_price(reference_entry + 2 * risk, "up") if risk else None,
                                "rr_3_target": _legal_price(reference_entry + 3 * risk, "up") if risk else None,
                                "next_resistance_reward": reward_at_resistance,
                                "next_resistance_rr": rr_at_resistance,
                                "formula": "風險＝進場－停損；RR＝(目標－進場)／(進場－停損)",
                                "verified": risk is not None},
        "execution_costs": {
            "commission_rate_each_side_percent": commission_rate * 100,
            "transaction_tax_sell_percent": transaction_tax_rate * 100,
            "slippage_each_side_percent": slippage_rate_each_side * 100,
            "assumed_round_trip_rate_percent": round((buy_cost_rate + sell_cost_rate) * 100, 4),
            "net_risk_per_share": net_risk,
            "net_reward_at_next_resistance": net_reward_at_resistance,
            "net_reward_at_planned_target": net_reward_at_planned_target,
            "cost_adjusted_rr": cost_adjusted_rr,
            "limitation": "未含個別券商折扣與大額委託的市場衝擊；次日開盤須依實際可成交價重算。",
        },
        "liquidity": {
            "average_turnover_20": round(float(average_turnover_20), 2) if average_turnover_20 else None,
            "max_position_value_at_1pct_adv": round(float(average_turnover_20) * 0.01, 2)
                if average_turnover_20 else None,
            "participation_cap_percent": 1,
        },
        "next_open_gate": {
            "maximum_entry_price": maximum_entry,
            "rule": "次日實際進場價不得高於最高允許進場價，且須以實際價重算成本後 RR。",
            "latest_observed_gap_percent": round(gap_percent, 4) if gap_percent is not None else None,
        },
        "price_tick_policy": "進場上限與目標向下取至合法跳動單位；停損與最低 RR 門檻向上取，避免低估風險或高估報酬。",
        "profit_management": "若第一減碼區達成，剩餘部位在『收盤跌破 MA5』或『自最高收盤回落 1.5 ATR』任一條件先觸發時，下一交易日開盤減碼；此規則仍待樣本外驗證。",
        "blocking_reasons": execution_blockers,
    }
