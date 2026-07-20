from app.themes import stock_themes


def test_stock_can_match_multiple_research_themes():
    assert "AI" in stock_themes("2454")
    assert "IC 設計" in stock_themes("2454")


def test_defense_drone_theme_is_separate():
    assert "軍工／無人機" in stock_themes("2634")
    assert stock_themes("1101") == []
