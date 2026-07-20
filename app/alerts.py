from __future__ import annotations

from datetime import date

from app.analysis import analyze
from app.database import Database
from app.revenue import analyze_revenue
from app.valuation import analyze_valuations


def _alert(symbol: str, name: str, category: str, severity: str, title: str,
           message: str, as_of: str | None) -> dict:
    return {"symbol": symbol, "name": name, "category": category, "severity": severity,
            "title": title, "message": message, "as_of": as_of}


def _institution_streak(rows: list[dict], key: str) -> tuple[int, int]:
    if not rows:
        return 0, 0
    latest = int(rows[-1].get(key) or 0)
    direction = 1 if latest > 0 else -1 if latest < 0 else 0
    if not direction:
        return 0, 0
    streak, total = 0, 0
    for row in reversed(rows):
        value = int(row.get(key) or 0)
        if (value > 0) != (direction > 0) or value == 0:
            break
        streak += 1
        total += value
    return streak * direction, total


def build_alerts(database: Database) -> dict:
    alerts = []
    watched = database.list_watchlist()
    for stock in watched:
        symbol, name = stock["symbol"], stock["name"]
        prices = database.get_prices(symbol, 100_000)
        technical = analyze(prices)
        if technical:
            rsi = technical.get("rsi_14")
            if rsi is not None and rsi >= 70:
                alerts.append(_alert(symbol, name, "技術面", "warning", "RSI 進入偏熱區",
                                     f"RSI 14 為 {rsi:.1f}，短線動能偏熱。", technical["as_of"]))
            elif rsi is not None and rsi <= 30:
                alerts.append(_alert(symbol, name, "技術面", "opportunity", "RSI 進入偏弱區",
                                     f"RSI 14 為 {rsi:.1f}，可能處於超賣或弱勢趨勢。", technical["as_of"]))
            distance = technical.get("from_all_time_high")
            if distance is not None and distance >= -.05:
                alerts.append(_alert(symbol, name, "價格", "info", "接近已同步歷史高點",
                                     f"目前距已同步最高收盤價僅 {abs(distance) * 100:.2f}%。", technical["as_of"]))
            if len(prices) >= 61:
                closes = [float(row["close"]) for row in prices]
                previous_sma = sum(closes[-61:-1]) / 60
                current_sma = sum(closes[-60:]) / 60
                if closes[-2] <= previous_sma and closes[-1] > current_sma:
                    alerts.append(_alert(symbol, name, "技術面", "opportunity", "向上突破季線",
                                         f"收盤價 {closes[-1]:.2f} 已由下往上突破 60 日均線。", technical["as_of"]))
                elif closes[-2] >= previous_sma and closes[-1] < current_sma:
                    alerts.append(_alert(symbol, name, "技術面", "warning", "跌破季線",
                                         f"收盤價 {closes[-1]:.2f} 已由上往下跌破 60 日均線。", technical["as_of"]))

        revenue_rows = database.get_monthly_revenues(symbol, 24)
        revenue = analyze_revenue(revenue_rows)
        if len(revenue_rows) >= 2:
            latest_yoy, previous_yoy = revenue_rows[-1].get("yoy_percent"), revenue_rows[-2].get("yoy_percent")
            if latest_yoy is not None and previous_yoy is not None and previous_yoy <= 0 < latest_yoy:
                alerts.append(_alert(symbol, name, "營收", "opportunity", "月營收年增轉正",
                                     f"營收 YoY 由 {previous_yoy:.1f}% 轉為 {latest_yoy:.1f}%。", revenue.get("as_of")))
        if revenue.get("is_record_high"):
            alerts.append(_alert(symbol, name, "營收", "opportunity", "月營收創資料期新高",
                                 "最新月營收高於資料庫內所有先前月份。", revenue.get("as_of")))

        valuation = analyze_valuations(database.get_valuations(symbol, 240))
        percentile = valuation.get("pe_percentile")
        if percentile is not None and valuation.get("observations", 0) >= 20:
            if percentile <= 20:
                alerts.append(_alert(symbol, name, "估值", "opportunity", "本益比位於歷史低檔",
                                     f"目前 PE 位於已同步資料的第 {percentile:.0f} 百分位。", valuation.get("as_of")))
            elif percentile >= 80:
                alerts.append(_alert(symbol, name, "估值", "warning", "本益比位於歷史高檔",
                                     f"目前 PE 位於已同步資料的第 {percentile:.0f} 百分位。", valuation.get("as_of")))

        institution_rows = database.get_institutional_trades(symbol, 30)
        for key, label in (("foreign_net", "外資"), ("trust_net", "投信")):
            streak, total = _institution_streak(institution_rows, key)
            if abs(streak) >= 3:
                action = "連續買超" if streak > 0 else "連續賣超"
                severity = "opportunity" if streak > 0 else "warning"
                alerts.append(_alert(symbol, name, "法人", severity, f"{label}{action}",
                                     f"{label}已{action} {abs(streak)} 日，累計 {total / 1000:,.0f} 張。",
                                     institution_rows[-1]["trade_date"]))

        for event in database.get_dividend_events(symbol, 20):
            try:
                days = (date.fromisoformat(event["ex_date"]) - date.today()).days
            except ValueError:
                continue
            if 0 <= days <= 30:
                alerts.append(_alert(symbol, name, "股利", "info", "除權息日接近",
                                     f"預計 {event['ex_date']} 除權息，距今 {days} 天。", event["ex_date"]))
                break

    order = {"warning": 0, "opportunity": 1, "info": 2}
    alerts.sort(key=lambda item: (order[item["severity"]], item["symbol"], item["category"]))
    return {"stocks_monitored": len(watched), "alerts": alerts,
            "counts": {key: sum(item["severity"] == key for item in alerts)
                       for key in ("warning", "opportunity", "info")}}
