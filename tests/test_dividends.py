from app.dividends import _normalize_tpex, _normalize_twse


def test_normalize_twse_dividend_event():
    row = {"Date": "1150717", "Code": "2330", "Exdividend": "息", "CashDividend": "5.00", "StockDividendRatio": ""}
    result = _normalize_twse(row)
    assert result["ex_date"] == "2026-07-17"
    assert result["cash_dividend"] == 5


def test_normalize_tpex_dividend_event():
    row = {"ExRrightsExDividendDate": "1150720", "SecuritiesCompanyCode": "2640", "ExRrightsExDividend": "除息", "CashDividend": "8.0", "StockDividendRatio": "0"}
    result = _normalize_tpex(row)
    assert result["market"] == "TPEx"
    assert result["cash_dividend"] == 8
