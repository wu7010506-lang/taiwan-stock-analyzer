from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from threading import Lock
from time import monotonic

import httpx


TWSE_INDEX_URL = "https://openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST"
TWSE_EVENTS_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
TPEX_EVENTS_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"
CACHE_SECONDS = 15 * 60
TWSE_INDEX_MONTH_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"

POSITIVE_WORDS = {
    "取得訂單": 14, "得標": 12, "庫藏股": 8, "增加投資": 6,
    "策略合作": 8, "現金股利": 5, "新產品": 6, "產能擴充": 6,
    "上修": 8, "獲利增加": 10, "營收增加": 8,
}
NEGATIVE_WORDS = {
    "重大損失": -15, "停工": -12, "違約": -18, "訴訟": -8,
    "裁罰": -10, "資安事件": -10, "火災": -12, "下修": -8,
    "虧損": -8, "減產": -9, "終止契約": -10, "董事辭任": -5,
}

_cache: tuple[float, dict] | None = None
_cache_lock = Lock()


def _number(value: object) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _event_value(row: dict, *names: str) -> str:
    for name in names:
        if row.get(name) is not None:
            return str(row[name]).strip()
    return ""


def _normalize_event(row: dict, market: str) -> dict | None:
    symbol = _event_value(row, "公司代號", "SecuritiesCompanyCode")
    title = _event_value(row, "主旨 ", "主旨", "Subject")
    if not symbol or not title:
        return None
    raw_score = sum(score for word, score in {**POSITIVE_WORDS, **NEGATIVE_WORDS}.items()
                    if word in title)
    return {
        "symbol": symbol, "market": market, "title": title,
        "date": _event_value(row, "發言日期", "Date"),
        "sentiment": max(-20, min(20, raw_score)),
    }


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [new - old for old, new in zip(values, values[1:])][-period:]
    gains = sum(max(value, 0) for value in changes) / period
    losses = sum(max(-value, 0) for value in changes) / period
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def _index_change(closes: list[float], days: int) -> float | None:
    return (closes[-1] / closes[-days - 1] - 1) * 100 if len(closes) > days else None


def _analyze_index(closes: list[float]) -> dict:
    """Separate market trend from chase risk after a rapid index expansion."""
    if not closes:
        return {"market_score": 50.0, "trend_score": 50.0, "overheat_score": 0.0,
                "regime": "資料暫時不可用"}
    latest = closes[-1]
    change_5d, change_20d, change_60d = (_index_change(closes, days)
                                         for days in (5, 20, 60))
    averages = {period: sum(closes[-period:]) / period if len(closes) >= period else None
                for period in (20, 60, 120)}
    deviations = {period: (latest / average - 1) * 100 if average else None
                  for period, average in averages.items()}
    rsi14 = _rsi(closes)
    history = closes[-250:]
    position = sum(value <= latest for value in history) / len(history) * 100

    trend = 50.0
    if averages[20] is not None:
        trend += 10 if latest >= averages[20] else -10
    if averages[60] is not None:
        trend += 10 if latest >= averages[60] else -10
    if change_20d is not None:
        trend += max(-20, min(20, change_20d * 1.5))
    elif change_5d is not None:
        trend += max(-15, min(15, change_5d * 2.5))
    if change_60d is not None:
        trend += max(-10, min(10, change_60d * .4))
    trend = max(0, min(100, trend))

    overheat, signals = 0.0, []
    if change_5d is not None and change_5d >= 5:
        points = 30 if change_5d >= 8 else 20
        overheat += points; signals.append(f"5日急漲 {change_5d:.1f}%")
    if change_20d is not None and change_20d >= 12:
        points = 30 if change_20d >= 20 else 20
        overheat += points; signals.append(f"20日漲幅 {change_20d:.1f}%")
    if deviations[20] is not None and deviations[20] >= 6:
        points = 25 if deviations[20] >= 10 else 15
        overheat += points; signals.append(f"高於20日均線 {deviations[20]:.1f}%")
    if deviations[60] is not None and deviations[60] >= 12:
        points = 25 if deviations[60] >= 20 else 15
        overheat += points; signals.append(f"高於60日均線 {deviations[60]:.1f}%")
    if rsi14 is not None and rsi14 >= 72:
        points = 25 if rsi14 >= 80 else 15
        overheat += points; signals.append(f"大盤 RSI {rsi14:.1f}")
    if len(history) >= 60 and position >= 90:
        overheat += 10; signals.append(f"指數位於歷史區間 {position:.0f}% 分位")
    overheat = min(100, overheat)
    adjusted = max(0, min(100, trend - overheat * .45))
    if overheat >= 70:
        adjusted = min(adjusted, 42); regime = "急漲後極度過熱"
    elif overheat >= 45:
        adjusted = min(adjusted, 52); regime = "偏多但過熱"
    elif overheat >= 25 and trend >= 60:
        adjusted = min(adjusted, 60); regime = "偏多但追價風險升高"
    else:
        regime = "偏多" if trend >= 60 else "偏空" if trend < 40 else "中性"
    high_60 = max(closes[-60:])
    return {"market_score": round(adjusted, 1), "trend_score": round(trend, 1),
            "overheat_score": round(overheat, 1), "regime": regime,
            "index_change_5d": change_5d, "index_change_20d": change_20d,
            "index_change_60d": change_60d, "index_rsi_14": rsi14,
            "distance_ma20_percent": deviations[20],
            "distance_ma60_percent": deviations[60],
            "history_position_percentile": position,
            "drawdown_from_60d_high_percent": (latest / high_60 - 1) * 100,
            "overheat_signals": signals}


def _month_starts(months: int = 7) -> list[date]:
    current = date.today().replace(day=1)
    result = []
    for _ in range(months):
        result.append(current)
        current = (current - timedelta(days=1)).replace(day=1)
    return list(reversed(result))


def _fetch_official_context() -> dict:
    with httpx.Client(timeout=8, follow_redirects=True,
                      headers={"User-Agent": "TaiwanStockAnalyzer/1.0"}) as client:
        errors = []
        def fetch(url: str) -> list[dict]:
            try:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, list) else []
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                errors.append(str(exc))
                return []
        index_rows = fetch(TWSE_INDEX_URL)
        # The OpenAPI feed usually contains only the current month. Pull enough
        # official monthly history to measure 20/60/120-day position and overheating.
        if len(index_rows) < 120:
            expanded = []
            for month in _month_starts():
                try:
                    response = client.get(TWSE_INDEX_MONTH_URL,
                                          params={"date": month.strftime("%Y%m%d"),
                                                  "response": "json"})
                    response.raise_for_status()
                    payload = response.json()
                    for values in payload.get("data", []):
                        if len(values) >= 5:
                            expanded.append({"Date": values[0], "ClosingIndex": values[4]})
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    errors.append(str(exc))
            if expanded:
                index_rows = expanded
        twse_rows = fetch(TWSE_EVENTS_URL)
        tpex_rows = fetch(TPEX_EVENTS_URL)

    closes = [_number(row.get("ClosingIndex")) for row in index_rows]
    closes = [value for value in closes if value is not None]
    latest = closes[-1] if closes else None
    market = _analyze_index(closes)
    events = []
    for row in twse_rows:
        event = _normalize_event(row, "TWSE")
        if event:
            events.append(event)
    for row in tpex_rows:
        event = _normalize_event(row, "TPEx")
        if event:
            events.append(event)
    available = bool(closes)
    return {
        "available": available,
        "as_of": _event_value(index_rows[-1], "Date") if index_rows else None,
        "index_close": latest, **market,
        "events": events,
        "sources": ["臺灣證券交易所發行量加權股價指數", "TWSE／TPEx 每日重大訊息"],
        "partial_errors": errors,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_market_context(force: bool = False) -> dict:
    """Return cached official market/event context; failures stay neutral and explainable."""
    global _cache
    with _cache_lock:
        if not force and _cache and monotonic() - _cache[0] < CACHE_SECONDS:
            return _cache[1]
        try:
            result = _fetch_official_context()
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            result = {
                "available": False, "as_of": None, "index_close": None,
                "index_change_5d": None, "index_change_20d": None,
                "market_score": 50.0, "regime": "資料暫時不可用", "events": [],
                "sources": ["官方資料暫時無法連線"], "error": str(exc),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        _cache = (monotonic(), result)
        return result
