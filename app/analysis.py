from __future__ import annotations

import math
from statistics import pstdev


def sma(values: list[float], period: int) -> float | None:
    return sum(values[-period:]) / period if len(values) >= period else None


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    factor = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = value * factor + result * (1 - factor)
    return result


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [new - old for old, new in zip(values, values[1:])][-period:]
    gains = sum(max(x, 0) for x in changes) / period
    losses = sum(max(-x, 0) for x in changes) / period
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def analyze(prices: list[dict]) -> dict:
    if not prices:
        return {}
    closes = [float(row["close"]) for row in prices]
    volumes = [float(row["volume"]) for row in prices]
    returns = [new / old - 1 for old, new in zip(closes, closes[1:]) if old]

    def period_return(days: int) -> float | None:
        return closes[-1] / closes[-days - 1] - 1 if len(closes) > days else None

    volatility = pstdev(returns[-20:]) * math.sqrt(252) if len(returns) >= 20 else None
    avg_volume = sma(volumes, 20)
    all_time_high_close = max(closes)
    all_time_high_index = max(range(len(closes)), key=closes.__getitem__)
    return {
        "symbol": prices[-1]["symbol"],
        "as_of": prices[-1]["trade_date"],
        "close": closes[-1],
        "sma_5": sma(closes, 5),
        "sma_20": sma(closes, 20),
        "sma_60": sma(closes, 60),
        "ema_12": ema(closes, 12),
        "ema_26": ema(closes, 26),
        "rsi_14": rsi(closes),
        "return_5d": period_return(5),
        "return_20d": period_return(20),
        "volatility_20d_annualized": volatility,
        "volume_ratio_20d": volumes[-1] / avg_volume if avg_volume else None,
        "all_time_high_close": all_time_high_close,
        "all_time_high_date": prices[all_time_high_index]["trade_date"],
        "from_all_time_high": closes[-1] / all_time_high_close - 1,
    }
