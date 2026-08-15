"""Evidence-only short-term technical analysis for an individual stock."""
from __future__ import annotations

from math import sqrt
from statistics import mean

from app.database import Database
from app.short_term_fundamentals import load_short_term_fundamental_assessment
from app.short_term_trade import build_breakout_trade_plan
from app.technical_indicators import _ema, calculate_technical_indicators


def _sma(values: list[float], period: int) -> float | None:
    return round(mean(values[-period:]), 4) if len(values) >= period else None


def _weekly_rows(rows: list[dict]) -> list[dict]:
    """Aggregate stored daily OHLCV into completed calendar weeks."""
    groups: dict[tuple[int, int], list[dict]] = {}
    for row in rows:
        stamp = row["trade_date"]
        year, week, _ = __import__("datetime").date.fromisoformat(stamp).isocalendar()
        groups.setdefault((year, week), []).append(row)
    result = []
    for group in groups.values():
        ordered = sorted(group, key=lambda item: item["trade_date"])
        result.append({"trade_date": ordered[-1]["trade_date"], "open": ordered[0]["open"],
                       "high": max(float(item["high"]) for item in ordered),
                       "low": min(float(item["low"]) for item in ordered),
                       "close": ordered[-1]["close"],
                       "volume": sum(float(item.get("volume") or 0) for item in ordered)})
    return result


def _label_trend(close: float, ma_short: float | None, ma_long: float | None) -> str:
    if ma_short is None or ma_long is None:
        return "unavailable"
    if close >= ma_short >= ma_long:
        return "bullish"
    if close <= ma_short <= ma_long:
        return "bearish"
    return "range_or_transition"


def _kd(rows: list[dict], period: int = 9) -> dict:
    if len(rows) < period + 3:
        return {"k": None, "d": None, "signal": "unavailable"}
    raw = []
    for index in range(period - 1, len(rows)):
        window = rows[index - period + 1:index + 1]
        high = max(float(item["high"]) for item in window)
        low = min(float(item["low"]) for item in window)
        raw.append((float(rows[index]["close"]) - low) / (high - low) * 100 if high > low else 50.0)
    k = mean(raw[-3:])
    d = mean(raw[-5:]) if len(raw) >= 5 else None
    signal = "bullish_cross" if d is not None and k > d and raw[-2] <= d else "bearish_cross" if d is not None and k < d and raw[-2] >= d else "neutral"
    return {"k": round(k, 4), "d": round(d, 4) if d is not None else None, "signal": signal}


def _candlestick(rows: list[dict]) -> dict:
    if len(rows) < 2:
        return {"pattern": "unavailable", "meaning": "insufficient_daily_candles"}
    previous, latest = rows[-2], rows[-1]
    opened, closed = float(latest["open"]), float(latest["close"])
    high, low = float(latest["high"]), float(latest["low"])
    body = abs(closed - opened)
    full_range = max(high - low, 0.000001)
    upper, lower = high - max(opened, closed), min(opened, closed) - low
    if body / full_range <= .1:
        return {"pattern": "doji", "meaning": "indecision_requires_next_session_confirmation"}
    if upper / full_range >= .45:
        return {"pattern": "long_upper_shadow", "meaning": "selling_pressure_or_failed_chase_risk"}
    if lower / full_range >= .45:
        return {"pattern": "long_lower_shadow", "meaning": "support_test_requires_confirmation"}
    prior_open, prior_close = float(previous["open"]), float(previous["close"])
    if closed > opened and prior_close < prior_open and opened <= prior_close and closed >= prior_open:
        return {"pattern": "bullish_engulfing", "meaning": "potential_reversal_requires_volume_and_structure_confirmation"}
    if closed < opened and prior_close > prior_open and opened >= prior_close and closed <= prior_open:
        return {"pattern": "bearish_engulfing", "meaning": "potential_reversal_requires_support_confirmation"}
    return {"pattern": "bullish_body" if closed > opened else "bearish_body", "meaning": "single_candle_not_a_standalone_signal"}


def _plain_short_term_conclusion(
    trade_plan: dict,
    as_of: str,
    fundamental_assessment: dict | None = None,
) -> dict:
    """Turn the fixed trade-plan checks into a short, non-technical answer."""
    checks = trade_plan.get("trigger_checks") or {}
    if trade_plan.get("status") == "insufficient_data" or not checks:
        return {
            "answer_code": "insufficient", "headline": "資料不足，現在不要判斷買進",
            "summary": "短線資料或 ATR／突破價不足，無法建立可信的進場、停損與目標。",
            "missing_conditions": trade_plan.get("blocking_reasons") or ["缺少完整短線交易資料"],
            "next_step": "先補齊至少 60 筆完整日 K 與必要技術指標。",
            "data_date": as_of, "scope": "只回答 3–10 個交易日的技術面，不代表基本面合格。",
        }

    missing = []
    breakout = checks.get("breakout", {})
    if not breakout.get("passed"):
        actual, required = breakout.get("actual"), breakout.get("required_above")
        missing.append(
            f"收盤尚未站上 {required:,.2f} 元（目前 {actual:,.2f} 元）"
            if actual is not None and required is not None else "收盤尚未突破 20 日高點"
        )
    trend = checks.get("trend", {})
    if not trend.get("passed"):
        missing.append("日線趨勢排列尚未轉為多頭")
    volume = checks.get("volume", {})
    if not volume.get("passed"):
        actual, required = volume.get("actual_ratio"), volume.get("required_ratio")
        missing.append(
            f"量能只有 20 日均量的 {actual:.2f} 倍，需要至少 {required:g} 倍"
            if actual is not None and required is not None else "成交量確認不足"
        )
    atr_risk = checks.get("atr_risk", {})
    if not atr_risk.get("passed"):
        missing.append("目前無法設定符合 1.5 ATR 上限的短線停損")

    common = {
        "data_date": as_of, "holding_period": "3–10 個交易日",
        "scope": "綜合基本面安全門檻與短線技術面；不代表合理價保證，也不保證獲利。",
        "reference_prices": None,
    }
    if fundamental_assessment and fundamental_assessment.get("status") == "data_pending":
        reasons = fundamental_assessment.get("blocking_reasons") or ["財報與估值尚未完成交叉驗證"]
        return {
            **common,
            "answer_code": "insufficient",
            "headline": "資料尚未一致，暫停買進判斷",
            "summary": "；".join(str(reason) for reason in reasons),
            "missing_conditions": reasons,
            "next_step": "先同步官方最新財報並重新計算近四季 EPS；資料一致前不判斷公司好壞，也不進入操作名單。",
            "technical_trigger_status": (
                "confirmed" if trade_plan.get("analysis_status") == "PASS" else "not_confirmed"
            ),
            "investment_status": "data_pending",
        }
    if fundamental_assessment and fundamental_assessment.get("passed") is False:
        reasons = fundamental_assessment.get("blocking_reasons") or ["基本面必要資料不足"]
        return {
            **common,
            "answer_code": "avoid",
            "headline": "不建議買進：基本面安全門檻未通過",
            "summary": "；".join(str(reason) for reason in reasons),
            "missing_conditions": reasons,
            "next_step": "即使技術突破成立也不列為買進候選；等待估值或本業獲利品質改善後再評估。",
            "technical_trigger_status": (
                "confirmed" if trade_plan.get("analysis_status") == "PASS" else "not_confirmed"
            ),
            "investment_status": "do_not_buy",
        }
    if missing:
        return {
            **common, "answer_code": "wait", "headline": "現在先不要買，等待條件完成",
            "summary": f"目前還差 {len(missing)} 項核心條件：{'；'.join(missing)}。",
            "missing_conditions": missing,
            "next_step": "等收盤後重新檢查；條件未完成前，不使用暫算 RR 當成買進依據。",
        }

    market_access = checks.get("market_access", {})
    if market_access and not market_access.get("passed"):
        return {
            **common, "answer_code": "avoid", "headline": "現在不要追價",
            "summary": "技術訊號雖已出現，但訊號日接近漲停，隔日可能買不到或買得太貴。",
            "missing_conditions": ["次日成交價尚未確認"],
            "next_step": "等待下一交易日實際開盤；高於最高允許進場價就放棄，不追價。",
        }

    chase_control = checks.get("chase_control", {})
    if chase_control and not chase_control.get("passed"):
        overextension = trade_plan.get("overextension_check") or {}
        signals = overextension.get("confirmation_signals") or []
        detail = "、".join(str(signal) for signal in signals)
        return {
            **common, "answer_code": "avoid", "headline": "突破成立，但現在不要追價",
            "summary": (
                f"5 日漲幅 {overextension.get('return_5d_percent'):.2f}%，且同時出現{detail}。"
                if overextension.get("return_5d_percent") is not None and detail
                else "短線漲幅與均線乖離已同時過度延伸。"
            ),
            "missing_conditions": ["等待急漲後的乖離收斂"],
            "next_step": "等待回檔守住突破區，或至少經過橫盤整理後，再用新價格重新建立停損與 RR。",
        }

    rr = checks.get("risk_reward", {})
    if not rr.get("passed"):
        actual, required = rr.get("actual"), rr.get("required")
        detail = (
            f"成本後 RR 只有 1：{actual:.2f}，低於目前市場要求的 1：{required:g}。"
            if actual is not None and required is not None
            else "獨立目標的預期空間不足，成本後 RR 未達要求。"
        )
        return {
            **common, "answer_code": "avoid", "headline": "現在不建議買，獲利空間不夠",
            "summary": detail, "missing_conditions": ["成本後風險報酬比不足"],
            "next_step": "不要為了通過 RR 自行調高目標價；等待價格或結構出現新的交易計畫。",
        }

    entry = trade_plan.get("reference_entry")
    maximum_entry = trade_plan.get("maximum_entry_price")
    return {
        **common, "answer_code": "conditional", "headline": "可列入下一交易日的條件式候選",
        "summary": (
            f"突破、趨勢、量能、ATR 停損與成本後 RR 已完成；但不是現在直接追價，"
            f"下一交易日實際成交價不得高於 {maximum_entry:,.2f} 元。"
            if maximum_entry is not None else
            "技術條件已完成，但下一交易日仍須以實際開盤價重算。"
        ),
        "missing_conditions": [],
        "next_step": "開盤前確認事件與成交可行性，並用實際價格重算 RR；任何一項失效就不進場。",
        "reference_prices": {
            "signal_close": entry, "maximum_entry": maximum_entry,
            "stop": trade_plan.get("stop"), "target": trade_plan.get("planned_target"),
            "cost_adjusted_rr": trade_plan.get("cost_adjusted_risk_reward"),
            "required_rr": trade_plan.get("required_rr"),
        },
        "risk_flags": trade_plan.get("soft_risks") or [],
    }


def _short_term_report(prices: list[dict], values: dict, as_of: str,
                       market_mode: str = "range",
                       fundamental_assessment: dict | None = None) -> dict:
    rows = [row for row in prices if all(row.get(key) is not None for key in ("open", "high", "low", "close"))]
    close = float(rows[-1]["close"])
    closes = [float(row["close"]) for row in rows]
    ma5, ma10, ma20, ma60 = (_sma(closes, period) for period in (5, 10, 20, 60))
    prior20, prior55 = rows[-21:-1], rows[-56:-1]
    recent_low = min(float(row["low"]) for row in rows[-20:])
    longer_low = min(float(row["low"]) for row in rows[-55:])
    prior20_high = max(float(row["high"]) for row in prior20) if len(prior20) >= 20 else None
    prior55_high = max(float(row["high"]) for row in prior55) if len(prior55) >= 55 else None
    support_candidates = sorted({value for value in (ma20, ma60, recent_low, longer_low) if value is not None and value <= close}, reverse=True)
    resistance_candidates = sorted({value for value in (ma20, ma60, prior20_high, prior55_high) if value is not None and value >= close})
    support_1 = support_candidates[0] if support_candidates else recent_low
    support_2 = next((value for value in support_candidates[1:] if value < support_1), longer_low if longer_low < support_1 else None)
    resistance_1 = resistance_candidates[0] if resistance_candidates else prior20_high
    resistance_2 = next((value for value in resistance_candidates[1:] if resistance_1 is not None and value > resistance_1), prior55_high if prior55_high and resistance_1 is not None and prior55_high > resistance_1 else None)
    recent, earlier = closes[-10:], closes[-20:-10]
    structure = "higher_high_higher_low" if max(recent) > max(earlier) and min(recent) >= min(earlier) else "lower_high_lower_low" if max(recent) < max(earlier) and min(recent) <= min(earlier) else "mixed_or_range"
    daily_trend = _label_trend(close, ma5, ma20)
    weekly = _weekly_rows(rows)
    weekly_closes = [float(row["close"]) for row in weekly]
    weekly_trend = _label_trend(close, _sma(weekly_closes, 5), _sma(weekly_closes, 10))
    volume_ratio = values.get("volume_ratio_20")
    latest_volume = float(rows[-1].get("volume") or 0)
    volume = {"relative_to_20d": volume_ratio, "state": "confirmed" if volume_ratio is not None and volume_ratio >= 1.2 else "contracted" if volume_ratio is not None and volume_ratio < .8 else "neutral",
              "price_change_percent": round((close / float(rows[-2]["close"]) - 1) * 100, 4),
              "interpretation": "price_volume_confirmation_required"}
    kd = _kd(rows)
    bollinger = {"upper": values.get("bollinger_upper"), "middle": values.get("bollinger_middle"), "lower": values.get("bollinger_lower"),
                 "position": "above_upper" if values.get("bollinger_upper") is not None and close > values["bollinger_upper"] else "below_lower" if values.get("bollinger_lower") is not None and close < values["bollinger_lower"] else "inside_bands"}
    macd_state = "bullish" if values.get("macd") is not None and values.get("macd_signal") is not None and values["macd"] > values["macd_signal"] else "bearish" if values.get("macd") is not None and values.get("macd_signal") is not None else "unavailable"
    rsi = values.get("rsi_14")
    conflicts = []
    if daily_trend == "bullish" and macd_state == "bearish": conflicts.append("trend_and_macd_conflict")
    if daily_trend == "bullish" and rsi is not None and rsi >= 70: conflicts.append("trend_but_rsi_overbought")
    trade_plan = build_breakout_trade_plan(rows, values, market_mode)
    healthy = daily_trend == "bullish" and weekly_trend != "bearish" and structure == "higher_high_higher_low"
    report = {
        "as_of": as_of, "horizon_sessions": "3-10", "research_only": True, "market_mode": market_mode,
        "trend": {"short": daily_trend, "medium": _label_trend(close, ma10, ma20), "long": _label_trend(close, ma20, ma60), "structure": structure,
                  "moving_averages": {"ma_5": ma5, "ma_10": ma10, "ma_20": ma20, "ma_60": ma60}, "strength": "strong" if healthy and values.get("adx_14") and values["adx_14"] >= 25 else "moderate" if healthy else "weak_or_mixed"},
        "support_resistance": {"support_1": support_1, "support_2": support_2, "resistance_1": resistance_1, "resistance_2": resistance_2,
                                "basis": ["supports_selected_only_below_current_price", "resistances_selected_only_above_current_price", "candidates=MA20_MA60_recent_lows_prior_highs"]},
        "volume": volume, "candlestick": _candlestick(rows),
        "indicators": {"macd_state": macd_state, "macd_histogram": values.get("macd_histogram"), "rsi_14": rsi, "kd": kd, "bollinger": bollinger, "conflicts": conflicts},
        "multi_timeframe": {"daily": daily_trend, "weekly": weekly_trend, "hour_60": "unavailable_no_intraday_data", "minute_15": "unavailable_no_intraday_data"},
        "strength": {"bulls": "strong" if healthy and volume["state"] == "confirmed" else "moderate" if healthy else "weak", "bears": "elevated" if daily_trend == "bearish" or structure == "lower_high_lower_low" else "contained", "chase_risk": "high" if (rsi or 0) >= 70 or bollinger["position"] == "above_upper" else "normal"},
        "trading_plan": trade_plan,
        "plain_conclusion": _plain_short_term_conclusion(
            trade_plan, as_of, fundamental_assessment=fundamental_assessment
        ),
        "fundamental_assessment": fundamental_assessment,
        "scenarios": {"bullish": {"condition": "close_above_resistance_1_with_volume_confirmation", "next_target": trade_plan.get("next_structural_resistance")}, "neutral": {"condition": "price_remains_between_support_1_and_resistance_1", "action": "wait"}, "bearish": {"condition": "daily_close_below_support_1", "next_support": support_2}},
        "limitations": ["僅使用日 K 與週 K 的價量資料；未提供正式 60 分鐘與 15 分鐘資料，因此不判斷。", "支撐、壓力、目標與停損是規則化參考價，不是執行指令。", "技術分析無法納入消息、財報、政策、跳空與實際成交價格。"]}
    presentation_labels = {
        "bullish": "偏多", "bearish": "偏空", "range_or_transition": "盤整／轉換中", "higher_high_higher_low": "高點、低點墊高", "lower_high_lower_low": "高點、低點下移", "mixed_or_range": "結構混合／區間整理", "strong": "強", "moderate": "中等", "weak": "弱", "weak_or_mixed": "偏弱／訊號混合", "elevated": "升高", "contained": "受控", "normal": "一般", "confirmed": "量能確認", "contracted": "量縮", "neutral": "中性", "long_upper_shadow": "長上影線", "long_lower_shadow": "長下影線", "doji": "十字線", "bullish_engulfing": "多頭吞沒", "bearish_engulfing": "空頭吞沒", "bullish_body": "紅 K", "bearish_body": "黑 K", "selling_pressure_or_failed_chase_risk": "賣壓增加／追價失敗風險", "support_test_requires_confirmation": "測試支撐，仍需確認", "potential_reversal_requires_volume_and_structure_confirmation": "可能轉折，仍須量能與結構確認", "single_candle_not_a_standalone_signal": "單一 K 線不足以單獨判斷", "bullish_cross": "黃金交叉", "bearish_cross": "死亡交叉", "above_upper": "突破布林上軌", "below_lower": "跌破布林下軌", "inside_bands": "布林通道內", "unavailable_no_intraday_data": "未提供正式分 K 資料", "wait_for_confirmation": "等待確認", "research_ready_if_confirmed": "確認條件後可研究", "below_1_to_1_5_or_unavailable": "低於 1：1.5 或資料不足", "meets_minimum_research_threshold": "達到研究門檻", "daily_close_above_resistance_1_and_volume_at_least_1_2x_20d": "日收盤突破第一壓力，且成交量至少為 20 日均量 1.2 倍", "close_above_resistance_1_with_volume_confirmation": "收盤突破第一壓力，且量能確認", "price_remains_between_support_1_and_resistance_1": "價格持續在第一支撐與第一壓力間", "daily_close_below_support_1": "日收盤跌破第一支撐", "wait": "等待", "trend_and_macd_conflict": "趨勢與 MACD 訊號衝突", "trend_but_rsi_overbought": "趨勢偏多但 RSI 過熱"}

    def present(value):
        if isinstance(value, dict):
            stable_code_keys = {"answer_code", "technical_trigger_status", "investment_status", "blocking_codes"}
            return {key: item if key in stable_code_keys else present(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [present(item) for item in value]
        return presentation_labels.get(value, value) if isinstance(value, str) else value

    return present(report)


def _returns(closes: list[float]) -> list[float]:
    return [current / previous - 1 for previous, current in zip(closes, closes[1:]) if previous > 0]


def _industry_relative_strength(database: Database, instrument: dict, as_of: str,
                                sessions: int = 60) -> dict:
    """Equal-weight peer return proxy, using only peers observable on the date."""
    industry = instrument.get("industry")
    if not industry:
        return {"status": "unavailable", "reason": "missing_industry_classification"}
    with database.connect() as connection:
        rows = connection.execute(
            """WITH ranked AS (
                   SELECT p.symbol, p.market, p.trade_date, p.close,
                          ROW_NUMBER() OVER (PARTITION BY p.symbol, p.market ORDER BY p.trade_date DESC) AS rank
                   FROM daily_prices p JOIN instruments i ON i.symbol=p.symbol AND i.market=p.market
                   WHERE i.industry=? AND p.trade_date<=?
               ) SELECT symbol, market, close, rank FROM ranked WHERE rank<=?""",
            (industry, as_of, sessions + 1),
        ).fetchall()
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["symbol"], row["market"]), []).append(dict(row))
    peer_returns = []
    target_return = None
    for (symbol, _), peer_rows in grouped.items():
        ordered = sorted(peer_rows, key=lambda row: row["rank"], reverse=True)
        if len(ordered) < sessions + 1 or not ordered[0]["close"]:
            continue
        result = float(ordered[-1]["close"]) / float(ordered[0]["close"]) - 1
        if symbol == instrument["symbol"]:
            target_return = result
        else:
            peer_returns.append(result)
    if target_return is None or len(peer_returns) < 5:
        return {"status": "unavailable", "reason": "insufficient_industry_peer_history",
                "peer_count": len(peer_returns)}
    benchmark = mean(peer_returns)
    return {"status": "available", "method": "equal_weight_industry_peer_return_proxy",
            "sessions": sessions, "peer_count": len(peer_returns),
            "stock_return_percent": round(target_return * 100, 4),
            "industry_return_percent": round(benchmark * 100, 4),
            "excess_return_percent": round((target_return - benchmark) * 100, 4),
            "limitations": ["Industry benchmark is an equal-weight peer proxy, not an investable sector index.",
                            "Delisted and historical classification changes are incomplete."]}


def _market_risk(database: Database, prices: list[dict], as_of: str) -> dict:
    closes = [float(row["close"]) for row in prices if row.get("close")]
    with database.connect() as connection:
        index_rows = [dict(row) for row in connection.execute(
            "SELECT trade_date,close FROM market_index_snapshots WHERE trade_date<=? ORDER BY trade_date DESC LIMIT 61",
            (as_of,),
        )]
    index_rows.reverse()
    index_by_date = {row["trade_date"]: float(row["close"]) for row in index_rows}
    aligned_stock, aligned_index = [], []
    for row in prices[-61:]:
        if row["trade_date"] in index_by_date and row.get("close"):
            aligned_stock.append(float(row["close"])); aligned_index.append(index_by_date[row["trade_date"]])
    stock_returns, index_returns = _returns(aligned_stock), _returns(aligned_index)
    historical_volatility = None
    beta = None
    if len(stock_returns) >= 20:
        historical_volatility = sqrt(mean(item * item for item in stock_returns) - mean(stock_returns) ** 2) * sqrt(252) * 100
    if len(stock_returns) >= 20 and len(stock_returns) == len(index_returns):
        index_mean = mean(index_returns)
        variance = mean((item - index_mean) ** 2 for item in index_returns)
        if variance:
            beta = mean((stock - mean(stock_returns)) * (index - index_mean)
                        for stock, index in zip(stock_returns, index_returns)) / variance
    return {"sessions": len(stock_returns), "historical_volatility_annualized_percent": round(historical_volatility, 4) if historical_volatility is not None else None,
            "beta_to_taiex_60d": round(beta, 4) if beta is not None else None,
            "limitations": ["Beta uses daily close returns and the stored TAIEX proxy; it is descriptive, not a forecast."]}


def _research_guidance(values: dict, trend: dict, relative_strength: dict, risk: dict) -> dict:
    """Explain the frozen evidence checklist without issuing a trade order."""
    positives, blockers, review_conditions = [], [], []
    if relative_strength.get("status") == "available" and (relative_strength.get("excess_return_percent") or 0) > 0:
        positives.append("近 60 日相對同業等權代理為正")
    if (values.get("macd_histogram") or 0) > 0:
        positives.append("MACD 柱狀體為正，短期動能有改善跡象")
    breakout_level = values.get("breakout_level_20d")
    if not values.get("breakout_20d"):
        blockers.append("尚未站上前 20 日高點")
        if breakout_level is not None:
            review_conditions.append(f"收盤站上 {breakout_level:,.2f} 的前 20 日高點後再檢查")
    if not values.get("volume_confirmation_20d"):
        blockers.append("未達 20 日平均量的 1.2 倍量能確認")
        review_conditions.append("同時確認當日成交量至少為 20 日均量的 1.2 倍")
    if not (trend.get("sma_20") and trend.get("sma_60") and trend["sma_20"] >= trend["sma_60"]):
        blockers.append("SMA20 尚未高於或等於 SMA60，趨勢排列未確認")
        review_conditions.append("確認 SMA20 ≥ SMA60，避免僅反彈而非趨勢恢復")
    if (risk.get("natr_14_percent") or 0) >= 7:
        blockers.append("NATR 至少 7%，近期波動偏高")
    if (risk.get("beta_to_taiex_60d") or 0) > 1.5:
        blockers.append("60 日 Beta 高於 1.5，對大盤波動較敏感")
    stance = "wait_for_confirmation" if blockers else "evidence_ready_for_review"
    return {"stance": stance, "label": "等待確認" if stance == "wait_for_confirmation" else "證據可重新檢查",
            "positives": positives, "blockers": blockers, "review_conditions": review_conditions,
            "risk_notice": "此為固定證據清單，不是買進、賣出或部位指令；短線策略尚未完成足夠樣本外與紙上驗證。"}


def build_short_analysis(database: Database, symbol: str, *, as_of: str | None = None,
                         market_mode: str = "range", market_context: dict | None = None) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError("instrument_not_found")
    prices = database.get_prices(symbol, 320, end_date=as_of)
    if len(prices) < 60:
        return {"symbol": symbol, "status": "insufficient_data", "input_rows": len(prices),
                "limitations": ["At least 60 daily OHLCV sessions are required; no neutral values are substituted."]}
    technical = calculate_technical_indicators(prices)
    values = technical["indicators"]
    closes = [float(row["close"]) for row in prices]
    close = closes[-1]
    atr = values.get("atr_14")
    high_52, low_52 = max(closes[-252:]), min(closes[-252:])
    donchian = {}
    for period in (20, 55):
        window = closes[-period:]
        donchian[str(period)] = {"high": round(max(window), 4), "low": round(min(window), 4),
                                 "position_percent": round((close - min(window)) / (max(window) - min(window)) * 100, 4)
                                 if max(window) > min(window) else None}
    trend = {"close": close, "ema_12": round(_ema(closes, 12), 4), "ema_20": round(_ema(closes, 20), 4),
             "ema_26": round(_ema(closes, 26), 4), "sma_20": values.get("sma_20"), "sma_60": values.get("sma_60"),
             "macd": values.get("macd"), "macd_signal": values.get("macd_signal"), "adx_14": values.get("adx_14"),
             "plus_di_14": values.get("plus_di_14"), "minus_di_14": values.get("minus_di_14")}
    relative_strength = _industry_relative_strength(database, instrument, technical["as_of"])
    risk = {"atr_14": atr, "natr_14_percent": values.get("natr_14"),
            "atr_2x_invalidation_price": round(close - 2 * atr, 4) if atr else None,
            "atr_3x_invalidation_price": round(close - 3 * atr, 4) if atr else None,
            **_market_risk(database, prices, technical["as_of"])}
    fundamental_assessment = load_short_term_fundamental_assessment(
        database,
        symbol,
        str(instrument.get("market")),
        str(technical["as_of"]),
        close,
    )
    return {"symbol": symbol, "name": instrument.get("name"), "market": instrument.get("market"),
            "industry": instrument.get("industry"), "as_of": technical["as_of"], "input_rows": len(prices),
            "research_only": True, "decision": "evidence_only_no_trade_instruction",
            "trend": trend, "relative_strength": relative_strength,
            "long_term_position": {"lookback_sessions": min(252, len(closes)), "high_52w": high_52, "low_52w": low_52,
                                   "distance_to_52w_high_percent": round((close / high_52 - 1) * 100, 4),
                                   "distance_to_52w_low_percent": round((close / low_52 - 1) * 100, 4)},
            "risk": risk, "research_guidance": _research_guidance(values, trend, relative_strength, risk),
            "fundamental_assessment": fundamental_assessment,
            "donchian": donchian, "existing_indicators": values,
            "short_term_report": _short_term_report(
                prices, values, technical["as_of"], market_mode, fundamental_assessment
            ),
            "short_term_market": {"mode": market_mode, "market_score": (market_context or {}).get("market_score"),
                                  "index_change_20d": (market_context or {}).get("index_change_20d")},
            "limitations": [*technical["limitations"], "This page presents evidence only; it does not recommend buying, selling, or a position size.",
                            "KD, Ichimoku, and VWAP are intentionally not displayed in this first version."]}
