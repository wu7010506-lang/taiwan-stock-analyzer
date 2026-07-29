from __future__ import annotations

from math import sqrt


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


def calculate_technical_indicators(rows: list[dict]) -> dict:
    """Return explainable end-of-series indicators, never fabricated defaults."""
    valid = [row for row in rows if row.get("close") is not None and float(row["close"]) > 0]
    closes = [float(row["close"]) for row in valid]
    volumes = [float(row.get("volume") or 0) for row in valid]
    latest = valid[-1] if valid else None
    sma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
    sma60 = _mean(closes[-60:]) if len(closes) >= 60 else None
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    macd = ema12 - ema26 if ema12 is not None and ema26 is not None else None
    # Signal line needs a time-series MACD; derive from each available prefix.
    macd_series = [(_ema(closes[:index], 12) - _ema(closes[:index], 26))
                   for index in range(26, len(closes) + 1)]
    signal = _ema(macd_series, 9) if len(macd_series) >= 9 else None
    middle = sma20
    deviation = (sqrt(sum((item - middle) ** 2 for item in closes[-20:]) / 20)
                 if middle is not None else None)
    volume20 = _mean(volumes[-20:]) if len(volumes) >= 20 else None
    close = float(latest["close"]) if latest else None
    return {
        "as_of": latest.get("trade_date") if latest else None,
        "input_rows": len(valid),
        "indicators": {
            "sma_20": round(sma20, 4) if sma20 is not None else None,
            "sma_60": round(sma60, 4) if sma60 is not None else None,
            "rsi_14": round(_rsi(closes), 4) if len(closes) > 14 else None,
            "macd": round(macd, 4) if macd is not None else None,
            "macd_signal": round(signal, 4) if signal is not None else None,
            "macd_histogram": round(macd - signal, 4) if macd is not None and signal is not None else None,
            "atr_14": round(_atr(valid), 4) if len(valid) > 14 else None,
            "bollinger_upper": round(middle + deviation * 2, 4) if deviation is not None else None,
            "bollinger_middle": round(middle, 4) if middle is not None else None,
            "bollinger_lower": round(middle - deviation * 2, 4) if deviation is not None else None,
            "volume_ratio_20": round(volumes[-1] / volume20, 4) if volume20 and volumes else None,
            "distance_to_60d_high_percent": round((close / max(closes[-60:]) - 1) * 100, 4)
                if close is not None and len(closes) >= 60 else None,
        },
        "availability": {
            "trend": len(closes) >= 60,
            "momentum": len(closes) >= 35,
            "volatility": len(closes) >= 20,
            "volume": len(volumes) >= 20,
        },
        "limitations": [
            "Indicators use only stored daily OHLCV through the displayed as-of date.",
            "Technical indicators describe price behaviour; they are not a guarantee of future returns.",
            "Missing warm-up history is returned as unavailable rather than assigned a neutral score.",
        ],
    }
