from __future__ import annotations

from statistics import mean

from app.analysis import analyze
from app.database import Database
from app.financials import analyze_financials
from app.revenue import analyze_revenue
from app.valuation import analyze_valuations


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _dimension(label: str, metrics: list[tuple[str, float | None, str]]) -> dict:
    available = [score for _, score, _ in metrics if score is not None]
    return {
        "label": label,
        "score": round(mean(available), 1) if available else None,
        "metrics": [{"label": name, "score": round(score, 1) if score is not None else None,
                     "detail": detail} for name, score, detail in metrics],
        "coverage": round(len(available) / len(metrics) * 100),
    }


def score_stock(database: Database, symbol: str) -> dict | None:
    instrument = database.get_instrument(symbol)
    if not instrument:
        return None
    prices = database.get_prices(symbol, 100_000)
    technical = analyze(prices)
    revenue = analyze_revenue(database.get_monthly_revenues(symbol, 36))
    financial = analyze_financials(database.get_financials(symbol, 20))
    valuation = analyze_valuations(database.get_valuations(symbol, 240))
    institutions = database.get_institutional_trades(symbol, 20)

    def percent(value: float | None) -> str:
        return "資料不足" if value is None else f"{value:.1f}%"

    eps, roe = financial.get("eps"), financial.get("annualized_roe_percent")
    margin, debt = financial.get("gross_margin_percent"), financial.get("debt_ratio_percent")
    fundamental = _dimension("基本面", [
        ("EPS", 100 if eps is not None and eps > 0 else 20 if eps is not None else None,
         "資料不足" if eps is None else f"每股盈餘 {eps:.2f}"),
        ("ROE", _clamp((roe + 5) / 25 * 100) if roe is not None else None, percent(roe)),
        ("毛利率", _clamp(margin / 40 * 100) if margin is not None else None, percent(margin)),
        ("負債比", 100 - _clamp(debt) if debt is not None else None, percent(debt)),
    ])

    yoy, rolling = revenue.get("yoy_percent"), revenue.get("rolling_3m_yoy_percent")
    consecutive = revenue.get("consecutive_positive_yoy_months")
    growth = _dimension("成長", [
        ("月營收 YoY", _clamp((yoy + 20) / 50 * 100) if yoy is not None else None, percent(yoy)),
        ("近 3 月營收 YoY", _clamp((rolling + 20) / 50 * 100) if rolling is not None else None, percent(rolling)),
        ("連續年增", _clamp(consecutive * 20) if consecutive is not None else None,
         "資料不足" if consecutive is None else f"連續 {consecutive} 個月"),
        ("營收創高", 100 if revenue.get("is_record_high") else 50 if revenue else None,
         "是" if revenue.get("is_record_high") else "否" if revenue else "資料不足"),
    ])

    pe_rank, pb_rank = valuation.get("pe_percentile"), valuation.get("pb_percentile")
    yield_rank = valuation.get("dividend_yield_percentile")
    valuation_score = _dimension("估值", [
        ("PE 歷史位置", 100 - pe_rank if pe_rank is not None else None,
         "資料不足" if pe_rank is None else f"第 {pe_rank:.0f} 百分位"),
        ("PB 歷史位置", 100 - pb_rank if pb_rank is not None else None,
         "資料不足" if pb_rank is None else f"第 {pb_rank:.0f} 百分位"),
        ("殖利率位置", yield_rank if yield_rank is not None else None,
         "資料不足" if yield_rank is None else f"第 {yield_rank:.0f} 百分位"),
    ])

    close, sma20, sma60 = technical.get("close"), technical.get("sma_20"), technical.get("sma_60")
    rsi, return20 = technical.get("rsi_14"), technical.get("return_20d")
    rsi_score = None if rsi is None else 80 if 45 <= rsi <= 65 else 60 if 30 <= rsi <= 70 else 35
    technical_score = _dimension("技術面", [
        ("20 日均線", 70 if close is not None and sma20 is not None and close > sma20 else 30 if sma20 is not None else None,
         "站上" if close is not None and sma20 is not None and close > sma20 else "跌破" if sma20 is not None else "資料不足"),
        ("60 日均線", 70 if close is not None and sma60 is not None and close > sma60 else 30 if sma60 is not None else None,
         "站上" if close is not None and sma60 is not None and close > sma60 else "跌破" if sma60 is not None else "資料不足"),
        ("RSI", rsi_score, "資料不足" if rsi is None else f"{rsi:.1f}"),
        ("20 日報酬", _clamp((return20 + .2) / .4 * 100) if return20 is not None else None,
         "資料不足" if return20 is None else f"{return20 * 100:+.1f}%"),
    ])

    latest = institutions[-1] if institutions else {}
    foreign, trust = latest.get("foreign_net"), latest.get("trust_net")
    def flow_score(value: int | None) -> float | None:
        return None if value is None else 65 if value > 0 else 35 if value < 0 else 50
    chip = _dimension("籌碼面", [
        ("外資買賣超", flow_score(foreign), "資料不足" if foreign is None else f"{foreign / 1000:+,.0f} 張"),
        ("投信買賣超", flow_score(trust), "資料不足" if trust is None else f"{trust / 1000:+,.0f} 張"),
    ])

    dimensions = [fundamental, growth, valuation_score, technical_score, chip]
    available = [item["score"] for item in dimensions if item["score"] is not None]
    overall = round(mean(available), 1) if available else None
    metrics = [metric for dimension in dimensions for metric in dimension["metrics"]]
    coverage = round(sum(metric["score"] is not None for metric in metrics) / len(metrics) * 100)
    strengths, risks = [], []
    for dimension in dimensions:
        if dimension["score"] is not None and dimension["score"] >= 70:
            strengths.append(f"{dimension['label']}相對較強（{dimension['score']:.0f} 分）")
        if dimension["score"] is not None and dimension["score"] < 40:
            risks.append(f"{dimension['label']}偏弱（{dimension['score']:.0f} 分）")
    if coverage < 60:
        risks.append(f"資料完整度僅 {coverage}%，評分可信度有限")
    label = "資料不足" if overall is None else "相對穩健" if overall >= 70 else "中性觀察" if overall >= 50 else "風險偏高"
    return {"symbol": symbol, "name": instrument["name"], "score": overall, "label": label,
            "coverage": coverage, "dimensions": dimensions, "strengths": strengths[:3],
            "risks": risks[:3], "method_version": "transparent-score-v1",
            "disclaimer": "分數是研究資料摘要，不是目標價、上漲機率或買賣建議。"}
