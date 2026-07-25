from app.market_context import _analyze_index


def test_market_context_penalizes_sudden_overheated_rally():
    stable = [100 + index * .05 for index in range(100)]
    surge = stable + [106, 109, 112, 116, 121, 126]
    result = _analyze_index(surge)
    assert result["trend_score"] >= 60
    assert result["overheat_score"] >= 70
    assert result["market_score"] <= 42
    assert result["regime"] == "急漲後極度過熱"
    assert result["overheat_signals"]


def test_market_context_keeps_orderly_uptrend_distinct_from_overheat():
    closes = [100 + index * .12 for index in range(140)]
    result = _analyze_index(closes)
    assert result["trend_score"] >= 60
    assert result["overheat_score"] < 45
    assert result["regime"] in {"偏多", "偏多但追價風險升高"}
