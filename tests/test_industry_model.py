from app.industry_model import industry_category, industry_label


def test_industry_categories_use_twse_codes():
    assert industry_category("17") == "financial"
    assert industry_category("24") == "semiconductor"
    assert industry_category("15") == "cyclical"
    assert industry_category("25") == "general"
    assert industry_label("17") == "金融專用模型"
