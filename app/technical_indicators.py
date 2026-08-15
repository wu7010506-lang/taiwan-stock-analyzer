from __future__ import annotations

from math import sqrt
from typing import Literal


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)
    for item in values[period:]:
        value = (item - value) * multiplier + value
    return value


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _atr(rows: list[dict], period: int = 14) -> float | None:
    if len(rows) <= period:
        return None
    ranges = []
    for index in range(1, len(rows)):
        high, low = float(rows[index]["high"]), float(rows[index]["low"])
        previous_close = float(rows[index - 1]["close"])
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    value = sum(ranges[:period]) / period
    for current in ranges[period:]:
        value = (value * (period - 1) + current) / period
    return value


def _directional_indicators(rows: list[dict], period: int = 14) -> dict[str, float | None]:
    """Calculate Wilder ADX and directional indicators without an optional binary dependency."""
    empty = {"adx_14": None, "plus_di_14": None, "minus_di_14": None}
    if len(rows) <= period * 2:
        return empty
    true_ranges: list[float] = []
    plus_moves: list[float] = []
    minus_moves: list[float] = []
    for index in range(1, len(rows)):
        current = rows[index]
        previous = rows[index - 1]
        high = float(current["high"])
        low = float(current["low"])
        previous_high = float(previous["high"])
        previous_low = float(previous["low"])
        previous_close = float(previous["close"])
        up_move = high - previous_high
        down_move = previous_low - low
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        plus_moves.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_moves.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus = sum(plus_moves[:period])
    smoothed_minus = sum(minus_moves[:period])
    dx_values: list[float] = []

    def current_values() -> tuple[float, float, float]:
        if smoothed_tr <= 0:
            return 0.0, 0.0, 0.0
        plus_di = 100 * smoothed_plus / smoothed_tr
        minus_di = 100 * smoothed_minus / smoothed_tr
        total = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / total if total else 0.0
        return plus_di, minus_di, dx

    plus_di, minus_di, dx = current_values()
    dx_values.append(dx)
    for index in range(period, len(true_ranges)):
        smoothed_tr = smoothed_tr - smoothed_tr / period + true_ranges[index]
        smoothed_plus = smoothed_plus - smoothed_plus / period + plus_moves[index]
        smoothed_minus = smoothed_minus - smoothed_minus / period + minus_moves[index]
        plus_di, minus_di, dx = current_values()
        dx_values.append(dx)
    if len(dx_values) < period:
        return empty
    adx = sum(dx_values[:period]) / period
    for dx in dx_values[period:]:
        adx = (adx * (period - 1) + dx) / period
    return {"adx_14": adx, "plus_di_14": plus_di, "minus_di_14": minus_di}


def _mfi(rows: list[dict], period: int = 14) -> float | None:
    if len(rows) <= period:
        return None
    typical = [
        (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3
        for row in rows
    ]
    positive: list[float] = []
    negative: list[float] = []
    for index in range(1, len(rows)):
        flow = typical[index] * float(rows[index].get("volume") or 0)
        positive.append(flow if typical[index] > typical[index - 1] else 0.0)
        negative.append(flow if typical[index] < typical[index - 1] else 0.0)
    positive_flow = sum(positive[-period:])
    negative_flow = sum(negative[-period:])
    if negative_flow == 0:
        return 100.0 if positive_flow else 50.0
    ratio = positive_flow / negative_flow
    return 100 - 100 / (1 + ratio)


def _talib_indicators(rows: list[dict]) -> dict | None:
    """Use TA-Lib when installed; return None so the built-in engine remains safe."""
    try:
        import numpy as np
        import talib
    except ImportError:
        return None
    try:
        close = np.asarray([float(row["close"]) for row in rows], dtype=float)
        high = np.asarray([float(row["high"]) for row in rows], dtype=float)
        low = np.asarray([float(row["low"]) for row in rows], dtype=float)
        volume = np.asarray([float(row.get("volume") or 0) for row in rows], dtype=float)
        macd, signal, histogram = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
        values = {
            "sma_5": talib.SMA(close, timeperiod=5)[-1],
            "sma_10": talib.SMA(close, timeperiod=10)[-1],
            "sma_20": talib.SMA(close, timeperiod=20)[-1],
            "sma_60": talib.SMA(close, timeperiod=60)[-1],
            "rsi_14": talib.RSI(close, timeperiod=14)[-1],
            "macd": macd[-1], "macd_signal": signal[-1], "macd_histogram": histogram[-1],
            "macd_histogram_change": histogram[-1] - histogram[-2],
            "atr_14": talib.ATR(high, low, close, timeperiod=14)[-1],
            "bollinger_upper": upper[-1], "bollinger_middle": middle[-1],
            "bollinger_lower": lower[-1],
            "obv": talib.OBV(close, volume)[-1],
            "adx_14": talib.ADX(high, low, close, timeperiod=14)[-1],
            "plus_di_14": talib.PLUS_DI(high, low, close, timeperiod=14)[-1],
            "minus_di_14": talib.MINUS_DI(high, low, close, timeperiod=14)[-1],
            "natr_14": talib.NATR(high, low, close, timeperiod=14)[-1],
            "mfi_14": talib.MFI(high, low, close, volume, timeperiod=14)[-1],
        }
        return {key: round(float(value), 4) if np.isfinite(value) else None
                for key, value in values.items()}
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def calculate_technical_indicators(rows: list[dict],
                                   engine: Literal["auto", "python", "talib"] = "auto") -> dict:
    """Return explainable end-of-series indicators, never fabricated defaults."""
    valid = [row for row in rows if row.get("close") is not None and float(row["close"]) > 0]
    closes = [float(row["close"]) for row in valid]
    volumes = [float(row.get("volume") or 0) for row in valid]
    latest = valid[-1] if valid else None
    sma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
    sma60 = _mean(closes[-60:]) if len(closes) >= 60 else None
    sma5 = _mean(closes[-5:]) if len(closes) >= 5 else None
    sma10 = _mean(closes[-10:]) if len(closes) >= 10 else None
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    ema20 = _ema(closes, 20)
    macd = ema12 - ema26 if ema12 is not None and ema26 is not None else None
    # Signal line needs a time-series MACD; derive from each available prefix.
    macd_series = [(_ema(closes[:index], 12) - _ema(closes[:index], 26))
                   for index in range(26, len(closes) + 1)]
    signal = _ema(macd_series, 9) if len(macd_series) >= 9 else None
    prior_macd_series = [(_ema(closes[:-1][:index], 12) - _ema(closes[:-1][:index], 26))
                         for index in range(26, len(closes))]
    prior_signal = _ema(prior_macd_series, 9) if len(prior_macd_series) >= 9 else None
    prior_macd = prior_macd_series[-1] if prior_macd_series else None
    histogram = macd - signal if macd is not None and signal is not None else None
    prior_histogram = (prior_macd - prior_signal
                       if prior_macd is not None and prior_signal is not None else None)
    middle = sma20
    deviation = (sqrt(sum((item - middle) ** 2 for item in closes[-20:]) / 20)
                 if middle is not None else None)
    volume20 = _mean(volumes[-20:]) if len(volumes) >= 20 else None
    close = float(latest["close"]) if latest else None
    def period_return(days: int) -> float | None:
        if close is None or len(closes) <= days or closes[-days - 1] <= 0:
            return None
        return (close / closes[-days - 1] - 1) * 100

    volume5 = _mean(volumes[-5:]) if len(volumes) >= 5 else None
    previous_close = closes[-2] if len(closes) >= 2 else None
    latest_open = float(latest["open"]) if latest and latest.get("open") is not None else None
    latest_high = float(latest["high"]) if latest and latest.get("high") is not None else None
    latest_low = float(latest["low"]) if latest and latest.get("low") is not None else None
    directional = _directional_indicators(valid)
    money_flow = _mfi(valid)
    builtin = {
        "sma_5": round(sma5, 4) if sma5 is not None else None,
        "sma_10": round(sma10, 4) if sma10 is not None else None,
        "sma_20": round(sma20, 4) if sma20 is not None else None,
        "sma_60": round(sma60, 4) if sma60 is not None else None,
        "rsi_14": round(_rsi(closes), 4) if len(closes) > 14 else None,
        "macd": round(macd, 4) if macd is not None else None,
        "macd_signal": round(signal, 4) if signal is not None else None,
        "macd_histogram": round(histogram, 4) if histogram is not None else None,
        "macd_histogram_change": round(histogram - prior_histogram, 4)
            if histogram is not None and prior_histogram is not None else None,
        "atr_14": round(_atr(valid), 4) if len(valid) > 14 else None,
        "bollinger_upper": round(middle + deviation * 2, 4) if deviation is not None else None,
        "bollinger_middle": round(middle, 4) if middle is not None else None,
        "bollinger_lower": round(middle - deviation * 2, 4) if deviation is not None else None,
        "volume_ratio_20": round(volumes[-1] / volume20, 4) if volume20 and volumes else None,
        "volume_ratio_5": round(volumes[-1] / volume5, 4) if volume5 and volumes else None,
        "return_1d_percent": round(period_return(1), 4) if period_return(1) is not None else None,
        "return_5d_percent": round(period_return(5), 4) if period_return(5) is not None else None,
        "return_10d_percent": round(period_return(10), 4) if period_return(10) is not None else None,
        "return_20d_percent": round(period_return(20), 4) if period_return(20) is not None else None,
        "latest_gap_percent": round((latest_open / previous_close - 1) * 100, 4)
            if latest_open is not None and previous_close else None,
        "latest_range_percent": round((latest_high - latest_low) / previous_close * 100, 4)
            if latest_high is not None and latest_low is not None and previous_close else None,
        "distance_to_60d_high_percent": round((close / max(closes[-60:]) - 1) * 100, 4)
            if close is not None and len(closes) >= 60 else None,
        "adx_14": round(directional["adx_14"], 4)
            if directional["adx_14"] is not None else None,
        "plus_di_14": round(directional["plus_di_14"], 4)
            if directional["plus_di_14"] is not None else None,
        "minus_di_14": round(directional["minus_di_14"], 4)
            if directional["minus_di_14"] is not None else None,
        "natr_14": round(_atr(valid) / close * 100, 4) if _atr(valid) and close else None,
        "mfi_14": round(money_flow, 4) if money_flow is not None else None,
        "keltner_middle_20": round(ema20, 4) if ema20 is not None else None,
        "keltner_upper_20": round(ema20 + 2 * _atr(valid), 4) if ema20 is not None and _atr(valid) else None,
        "keltner_lower_20": round(ema20 - 2 * _atr(valid), 4) if ema20 is not None and _atr(valid) else None,
    }
    talib_values = _talib_indicators(valid) if engine != "python" else None
    active_engine = "talib" if talib_values is not None and engine != "python" else "python"
    if talib_values:
        builtin.update(talib_values)
    prior_high_20 = max(closes[-21:-1]) if len(closes) >= 21 else None
    breakout = bool(prior_high_20 is not None and close is not None and close > prior_high_20)
    volume_confirmed = bool(volume20 and volumes and volumes[-1] >= volume20 * 1.2)
    trend_confirmed = bool(sma20 is not None and sma60 is not None and close is not None
                           and close >= sma20 >= sma60)
    builtin.update({
        "breakout_20d": breakout,
        "breakout_level_20d": round(prior_high_20, 4) if prior_high_20 is not None else None,
        "volume_confirmation_20d": volume_confirmed,
        "trend_confirmation": trend_confirmed,
    })
    return {
        "as_of": latest.get("trade_date") if latest else None,
        "input_rows": len(valid),
        "engine": active_engine,
        "requested_engine": engine,
        "talib_available": _talib_indicators(valid) is not None,
        "indicators": builtin,
        "availability": {
            "trend": len(closes) >= 60,
            "momentum": len(closes) >= 35,
            "volatility": len(closes) >= 20,
            "volume": len(volumes) >= 20,
            "trend_strength": len(closes) >= 28,
            "money_flow": len(closes) >= 15 and any(volumes),
        },
        "limitations": [
            "Indicators use only stored daily OHLCV through the displayed as-of date.",
            "Technical indicators describe price behaviour; they are not a guarantee of future returns.",
            "Missing warm-up history is returned as unavailable rather than assigned a neutral score.",
            "Breakout and volume confirmation are research conditions, not standalone buy signals.",
            "ADX/DI and MFI use TA-Lib when available and Wilder-compatible built-ins otherwise.",
        ],
    }
