from app.ownership import analyze_ownership, normalize_tdcc_row


def test_normalize_tdcc_row_handles_bom_date_key():
    row = {"\ufeff資料日期": "20260717", "證券代號": "2330", "持股分級": "1",
           "人數": "1,234", "股數": "567,890", "占集保庫存數比例%": "1.25"}
    result = normalize_tdcc_row(row)
    assert result["data_date"] == "2026-07-17"
    assert result["holders"] == 1234
    assert result["percentage"] == 1.25


def test_analysis_groups_holding_levels_without_claiming_identity():
    rows = [
        {"symbol": "2330", "data_date": "2026-07-17", "holding_level": level,
         "holders": 10, "shares": 1000, "percentage": percentage, "source": "TDCC"}
        for level, percentage in [(1, 10), (5, 5), (6, 8), (10, 7), (11, 20), (15, 50)]
    ]
    result = analyze_ownership(rows)
    assert result["small"]["percentage"] == 15
    assert result["medium"]["percentage"] == 15
    assert result["large"]["percentage"] == 70
    assert result["concentration_label"] == "持股較集中"
    assert "大額帳戶不等於投信" in result["disclaimer"]
