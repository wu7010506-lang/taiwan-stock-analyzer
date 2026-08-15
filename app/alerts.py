from __future__ import annotations

from datetime import date

from app.analysis import analyze
from app.database import Database
from app.revenue import analyze_revenue
from app.valuation import analyze_valuations
from app.recommendations import recommend_stocks


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


def _short_trade_decision(database: Database, symbol: str, name: str,
                          context: dict) -> dict:
    """Short-horizon timing model using price, volume, flow and market regime."""
    score, evidence, positive, negative = 50, 0, [], []
    prices = database.get_prices(symbol, 100_000)
    technical = analyze(prices)
    if technical and technical.get("rsi_14") is not None:
        evidence += 1
        rsi = technical["rsi_14"]
        if rsi <= 35:
            score += 6; positive.append(f"RSI {rsi:.1f} 位於低檔，但仍需確認止跌")
        elif rsi >= 70:
            score -= 10; negative.append(f"RSI {rsi:.1f} 偏熱")
    if len(prices) >= 60:
        evidence += 1
        close = float(prices[-1]["close"])
        sma60 = sum(float(row["close"]) for row in prices[-60:]) / 60
        if close >= sma60:
            score += 10; positive.append("股價位於60日均線之上")
        else:
            score -= 10; negative.append("股價位於60日均線之下")
    if len(prices) >= 6:
        evidence += 1
        momentum = (float(prices[-1]["close"]) / float(prices[-6]["close"]) - 1) * 100
        if 2 <= momentum <= 8:
            score += 8; positive.append(f"近5日上漲 {momentum:.1f}%，動能正向但未過熱")
        elif momentum >= 10:
            score -= 6; negative.append(f"近5日上漲 {momentum:.1f}%，短線追價風險偏高")
        elif momentum <= -5:
            score -= 8; negative.append(f"近5日下跌 {abs(momentum):.1f}%，趨勢仍弱")
    if len(prices) >= 20:
        recent_volume = sum(float(row["volume"]) for row in prices[-5:]) / 5
        base_volume = sum(float(row["volume"]) for row in prices[-20:]) / 20
        if base_volume > 0:
            evidence += 1
            volume_ratio = recent_volume / base_volume
            if volume_ratio >= 1.5:
                positive.append(f"近5日量能為20日均量 {volume_ratio:.1f} 倍")

    revenues = database.get_monthly_revenues(symbol, 24)
    if revenues and revenues[-1].get("yoy_percent") is not None:
        evidence += 1
        yoy = float(revenues[-1]["yoy_percent"])
        if yoy >= 10:
            score += 6; positive.append(f"月營收年增 {yoy:.1f}%")
        elif yoy < 0:
            score -= 6; negative.append(f"月營收年減 {abs(yoy):.1f}%")

    valuation = analyze_valuations(database.get_valuations(symbol, 240))
    percentile = valuation.get("pe_percentile")
    if percentile is not None and valuation.get("observations", 0) >= 20:
        evidence += 1
        if percentile <= 25:
            score += 4; positive.append("本益比位於自身歷史低檔")
        elif percentile >= 80:
            score -= 4; negative.append("本益比位於自身歷史高檔")

    institutions = database.get_institutional_trades(symbol, 5)
    if institutions:
        evidence += 1
        foreign = sum(int(row.get("foreign_net") or 0) for row in institutions)
        trust = sum(int(row.get("trust_net") or 0) for row in institutions)
        combined = foreign + trust
        if combined > 0:
            score += 7; positive.append(f"外資與投信近5日合計買超 {combined / 1000:,.0f} 張")
        elif combined < 0:
            score -= 7; negative.append(f"外資與投信近5日合計賣超 {abs(combined) / 1000:,.0f} 張")

    market_score = float(context.get("market_score", 50))
    overheat_score = float(context.get("overheat_score", 0))
    evidence += 1
    if overheat_score >= 70:
        score -= 18; negative.append(f"大盤急漲後極度過熱（{overheat_score:.0f}），避免追價")
    elif overheat_score >= 45:
        score -= 10; negative.append(f"大盤偏多但過熱（{overheat_score:.0f}），回檔風險升高")
    elif overheat_score >= 25:
        score -= 5; negative.append(f"大盤追價風險升高（{overheat_score:.0f}）")
    elif market_score >= 60:
        score += 6; positive.append(f"整體市場偏多（{market_score:.0f} 分）")
    elif market_score < 40:
        score -= 8; negative.append(f"整體市場偏弱（{market_score:.0f} 分）")

    score = max(0, min(100, score))
    if evidence < 3:
        action, tone = "資料不足", "insufficient"
    elif score >= 65:
        action, tone = "短線可買進研究", "buy"
    elif score <= 35:
        action, tone = "短線考慮賣出／避開", "sell"
    else:
        action, tone = "短線續抱／等待", "hold"
    return {
        "symbol": symbol, "name": name, "action": action, "tone": tone,
        "score": round(score, 1), "confidence": "高" if evidence >= 5 else "中" if evidence >= 3 else "低",
        "evidence_count": evidence, "positive_reasons": positive[:3],
        "risk_reasons": negative[:3],
        "as_of": technical.get("as_of") if technical else None,
        "mode": "short", "horizon": "數日至數週", "model_version": "alert-short-v2",
        "can_buy": tone == "buy", "can_sell": tone == "sell",
        "disclaimer": "未納入你的持有成本、部位大小與風險承受度，不是自動交易指令。",
    }


def _long_trade_decision(database: Database, symbol: str, name: str,
                         recommendation: dict | None) -> dict:
    """Long-horizon decision based on evidence-layered fundamentals and valuation."""
    if not recommendation:
        return {"symbol": symbol, "name": name, "action": "長線資料不足",
                "tone": "insufficient", "score": 50, "confidence": "低",
                "evidence_count": 0, "positive_reasons": [],
                "risk_reasons": ["尚未具備五年財報與足夠現金流資料"],
                "as_of": None, "mode": "long", "horizon": "一年以上",
                "model_version": "alert-long-v1", "can_buy": False, "can_sell": False,
                "disclaimer": "未納入你的持有成本、部位大小與風險承受度，不是自動交易指令。"}
    score = float(recommendation["score"])
    positive, negative = [], list(recommendation.get("invalidation_conditions") or [])
    dimensions = [
        ("企業品質", recommendation.get("business_quality_score")),
        ("現金流／資本品質", recommendation.get("cashflow_quality_score")),
        ("獲利持續性", recommendation.get("durability_score")),
        ("估值", recommendation.get("value_score")),
        ("風險韌性", recommendation.get("risk_resilience_score")),
    ]
    positive.extend(f"{label} {value:.0f} 分" for label, value in dimensions
                    if value is not None and value >= 65)
    negative.extend(f"{label}僅 {value:.0f} 分" for label, value in dimensions
                    if value is not None and value < 45)
    prices = database.get_prices(symbol, 100_000)
    technical = analyze(prices)
    if len(prices) >= 60:
        close = float(prices[-1]["close"])
        sma60 = sum(float(row["close"]) for row in prices[-60:]) / 60
        if close < sma60:
            score -= 4; negative.append("股價跌破60日均線，長線條件仍需等待價格止穩")
    if recommendation.get("speculation_risk") == "高":
        score -= 5; negative.append("上漲可能高度受法人資金推動，追價風險高")
    score = max(0, min(100, score))
    evidence = 7
    if score >= 70 and not any("缺乏安全邊際" in reason for reason in negative):
        action, tone = "長線可分批買進研究", "buy"
    elif score < 50:
        action, tone = "長線考慮賣出／避開", "sell"
    else:
        action, tone = "長線續抱／等待更佳價格", "hold"
    return {"symbol": symbol, "name": name, "action": action, "tone": tone,
            "score": round(score, 1), "confidence": "高" if recommendation.get("evidence_years", 0) >= 5 else "中",
            "evidence_count": evidence, "positive_reasons": positive[:4],
            "risk_reasons": negative[:4], "as_of": recommendation.get("trade_date"),
            "mode": "long", "horizon": "一年以上", "model_version": "alert-long-v1",
            "can_buy": tone == "buy", "can_sell": tone == "sell",
            "industry_model": recommendation.get("industry_model"),
            "disclaimer": "未納入你的持有成本、部位大小與風險承受度，不是自動交易指令。"}


def _apply_position_context(decision: dict, stock: dict) -> dict:
    result = dict(decision)
    result.update({"is_held": stock.get("is_held", False),
                   "average_cost": stock.get("average_cost"), "shares": stock.get("shares"),
                   "unrealized_return": stock.get("unrealized_return"),
                   "stop_loss": stock.get("stop_loss"), "target_price": stock.get("target_price"),
                   "investment_horizon": stock.get("investment_horizon")})
    if not stock.get("is_held"):
        result["position_status"] = "尚未持有"
        return result
    result["position_status"] = "已持有"
    pnl = stock.get("unrealized_return")
    if pnl is not None:
        label = "獲利" if pnl >= 0 else "虧損"
        reason = f"目前部位{label} {abs(pnl) * 100:.1f}%（成本 {stock['average_cost']:.2f}）"
        (result["positive_reasons"] if pnl >= 0 else result["risk_reasons"]).insert(0, reason)
    if stock.get("stop_triggered"):
        result.update({"action": "已跌破停損價，考慮執行風險控制", "tone": "sell",
                       "can_buy": False, "can_sell": True})
        result["risk_reasons"].insert(0, f"現價已低於停損價 {stock['stop_loss']:.2f}")
    elif stock.get("target_reached"):
        result.update({"action": "已達目標價，考慮分批停利", "tone": "sell",
                       "can_sell": True})
        result["positive_reasons"].insert(0, f"現價已達目標價 {stock['target_price']:.2f}")
    elif result.get("tone") == "buy":
        prefix = "長線" if result.get("mode") == "long" else "短線"
        result["action"] = f"{prefix}可續抱／分批加碼研究"
    result["positive_reasons"] = result["positive_reasons"][:4]
    result["risk_reasons"] = result["risk_reasons"][:4]
    return result


def build_alerts(database: Database, mode: str = "short", context: dict | None = None) -> dict:
    if mode not in {"short", "long"}:
        raise ValueError("mode must be short or long")
    context = context or {"market_score": 50, "regime": "neutral", "events": []}
    alerts = []
    decisions = []
    watched = database.list_watchlist()
    long_recommendations = {}
    if mode == "long":
        long_recommendations = {row["symbol"]: row for row in recommend_stocks(
            database, limit=5000, min_completeness=0, profile="evidence_based", context=context
        )}
    for stock in watched:
        symbol, name = stock["symbol"], stock["name"]
        decision = (
            _long_trade_decision(database, symbol, name, long_recommendations.get(symbol))
            if mode == "long" else _short_trade_decision(database, symbol, name, context)
        )
        decisions.append(_apply_position_context(decision, stock))
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
    return {"stocks_monitored": len(watched), "mode": mode,
            "horizon": "數日至數週" if mode == "short" else "一年以上",
            "market_score": context.get("market_score"), "market_regime": context.get("regime"),
            "alerts": alerts, "decisions": decisions,
            "counts": {key: sum(item["severity"] == key for item in alerts)
                       for key in ("warning", "opportunity", "info")}}
