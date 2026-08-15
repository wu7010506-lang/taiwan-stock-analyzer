from __future__ import annotations

"""Explainable technical timing for qualified long-term candidates.

The layer intentionally does not alter vNext's quality/value rank.  It answers
the separate question of whether current price action supports a new entry.
"""

from app.technical_indicators import calculate_technical_indicators


def _number(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _candle_pattern(rows: list[dict]) -> str | None:
    if len(rows) < 2:
        return None
    previous, latest = rows[-2], rows[-1]
    values = [[_number(row.get(key)) for key in ("open", "high", "low", "close")]
              for row in (previous, latest)]
    if any(value is None for row in values for value in row):
        return None
    (previous_open, _, _, previous_close), (opened, high, low, close) = values
    body, full_range = abs(close - opened), high - low
    if full_range > 0 and high - max(opened, close) >= max(body * 2, full_range * .45):
        return "long_upper_shadow"
    if (previous_close < previous_open and close > opened
            and opened <= previous_close and close >= previous_open):
        return "bullish_engulfing"
    if (previous_close > previous_open and close < opened
            and opened >= previous_close and close <= previous_open):
        return "bearish_engulfing"
    return None


def assess_technical_timing(prices: list[dict], market_context: dict | None = None) -> dict:
    """Assess trend, relative strength, volume and extension without invented data."""
    market_context = market_context or {}
    technical = calculate_technical_indicators(prices)
    values = technical["indicators"]
    rows = [row for row in prices if (_number(row.get("close")) or 0) > 0]
    if len(rows) < 60:
        return {"status": "insufficient_data", "signal": "unavailable", "score": None,
                "as_of": technical["as_of"], "input_rows": len(rows), "reasons": [],
                "risks": ["technical_history_under_60_sessions"], "indicators": values,
                "candle_pattern": _candle_pattern(rows), "limitations": technical["limitations"]}

    close = _number(rows[-1]["close"])
    sma20, sma60, atr = (_number(values.get(key)) for key in ("sma_20", "sma_60", "atr_14"))
    stock_return_20 = (close / _number(rows[-21]["close"]) - 1) * 100
    index_return_20 = _number(market_context.get("index_change_20d"))
    relative_strength = stock_return_20 - index_return_20 if index_return_20 is not None else None
    extension = (close / sma20 - 1) * 100 if sma20 else None
    atr_percent = atr / close * 100 if atr and close else None
    adx, natr, mfi = (_number(values.get(key)) for key in ("adx_14", "natr_14", "mfi_14"))
    keltner_upper = _number(values.get("keltner_upper_20"))
    trend = bool(close and sma20 and sma60 and close >= sma20 >= sma60)
    breakout = bool(values.get("breakout_20d") and values.get("volume_confirmation_20d"))
    overextended = bool(extension is not None and atr_percent is not None and extension >= max(8, atr_percent * 3))
    keltner_extended = bool(keltner_upper and close and close > keltner_upper
                             and extension is not None and extension >= 5)
    reasons, risks, points = [], [], 0
    if trend:
        points += 40; reasons.append("technical_trend_confirmed")
    else:
        risks.append("technical_trend_not_confirmed")
    if relative_strength is None:
        risks.append("relative_strength_unavailable")
    elif relative_strength >= 0:
        points += 25; reasons.append("relative_strength_positive")
    else:
        risks.append("relative_strength_negative")
    if breakout:
        points += 20; reasons.append("breakout_volume_confirmed")
    elif values.get("breakout_20d"):
        risks.append("breakout_without_volume_confirmation")
    else:
        points += 10
    if adx is None:
        risks.append("trend_strength_unavailable")
    elif adx >= 20:
        points += 10; reasons.append("trend_strength_confirmed")
    else:
        risks.append("trend_strength_weak")
    if overextended or keltner_extended:
        risks.append("technical_overextended")
    else:
        points += 15; reasons.append("technical_extension_within_range")
    pattern = _candle_pattern(rows)
    if pattern in {"long_upper_shadow", "bearish_engulfing"}:
        risks.append(pattern)
    if mfi is not None and mfi >= 80:
        risks.append("money_flow_overheated")
    if natr is not None and natr >= 7:
        risks.append("volatility_extreme")
    elif natr is not None and natr >= 4:
        risks.append("volatility_high")
    position_multiplier = .25 if (natr is not None and natr >= 7) else .5 if (
        (natr is not None and natr >= 4) or (mfi is not None and mfi >= 80)) else 1.0
    signal = "favorable" if (trend and not overextended and not keltner_extended
                               and "relative_strength_negative" not in risks
                               and "trend_strength_weak" not in risks) else "wait"
    if not trend and relative_strength is not None and relative_strength < -5:
        signal = "avoid"
    return {"status": "available", "signal": signal, "score": points,
            "as_of": technical["as_of"], "input_rows": len(rows), "reasons": reasons, "risks": risks,
            "candle_pattern": pattern,
            "position_multiplier": position_multiplier,
            "indicators": {"close": round(close, 4), "sma_20": sma20, "sma_60": sma60, "atr_14": atr,
                           "atr_percent": round(atr_percent, 3) if atr_percent else None,
                           "distance_sma20_percent": round(extension, 3) if extension is not None else None,
                           "stock_return_20d_percent": round(stock_return_20, 3),
                           "index_return_20d_percent": round(index_return_20, 3) if index_return_20 is not None else None,
                           "relative_strength_20d_percent": round(relative_strength, 3) if relative_strength is not None else None,
                           "breakout_20d": values.get("breakout_20d"),
                           "volume_confirmation_20d": values.get("volume_confirmation_20d"),
                           "adx_14": adx, "plus_di_14": values.get("plus_di_14"),
                           "minus_di_14": values.get("minus_di_14"), "natr_14": natr,
                           "mfi_14": mfi, "keltner_upper_20": keltner_upper},
            "limitations": [*technical["limitations"],
                            "Technical timing is an entry/risk aid and does not change vNext quality/value ranking.",
                            "Candlestick descriptions are supplementary, never standalone buy signals."]}
