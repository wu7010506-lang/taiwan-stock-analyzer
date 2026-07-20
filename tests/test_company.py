from app.company import company_profile


def test_company_profile_describes_official_industry():
    result = company_profile({"symbol": "2330", "industry": "24", "website": "https://example.com"})
    assert result["industry_name"] == "半導體業"
    assert "晶圓製造" in result["business_summary"]
    assert result["website"] == "https://example.com"


def test_company_profile_has_honest_fallback():
    result = company_profile({"symbol": "9999", "industry": None})
    assert result["industry_name"] == "產業未分類"
    assert "公司官網" in result["business_summary"]
