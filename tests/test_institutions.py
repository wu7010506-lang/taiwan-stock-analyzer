from app.institutions import normalize_tpex, normalize_twse


def test_normalize_twse_institutional_trade():
    fields = ["證券代號", "外陸資買進股數(不含外資自營商)",
              "外陸資賣出股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)",
              "投信買進股數", "投信賣出股數", "投信買賣超股數"]
    payload = {"date": "20260720", "fields": fields,
               "data": [["2330", "2,000", "1,000", "1,000", "500", "800", "-300"]]}
    row = normalize_twse(payload, "2330")
    assert row["trade_date"] == "2026-07-20"
    assert row["foreign_net"] == 1000
    assert row["trust_net"] == -300


def test_normalize_tpex_institutional_trade():
    row = normalize_tpex({
        "Date": "1150720", "SecuritiesCompanyCode": "6488",
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy": "3000",
        " Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell": "1000",
        "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "2000",
        "SecuritiesInvestmentTrustCompanies-TotalBuy": "4000",
        "SecuritiesInvestmentTrustCompanies-TotalSell": "500",
        "SecuritiesInvestmentTrustCompanies-Difference": "3500",
    })
    assert row["trade_date"] == "2026-07-20"
    assert row["foreign_buy"] == 3000
    assert row["trust_net"] == 3500
