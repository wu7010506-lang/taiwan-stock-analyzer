from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from app.config import settings
from app.database import Database
from app.providers import _parse_date


def _integer(value: object) -> int:
    try:
        return int(Decimal(str(value or "0").replace(",", "").strip()))
    except InvalidOperation:
        return 0


def normalize_twse(payload: dict, symbol: str) -> dict | None:
    fields = payload.get("fields", [])
    for values in payload.get("data", []):
        row = dict(zip(fields, values))
        if str(row.get("證券代號", "")).strip() != symbol:
            continue
        return {
            "symbol": symbol, "market": "TWSE",
            "trade_date": _parse_date(str(payload["date"])).isoformat(),
            "foreign_buy": _integer(row.get("外陸資買進股數(不含外資自營商)")),
            "foreign_sell": _integer(row.get("外陸資賣出股數(不含外資自營商)")),
            "foreign_net": _integer(row.get("外陸資買賣超股數(不含外資自營商)")),
            "trust_buy": _integer(row.get("投信買進股數")),
            "trust_sell": _integer(row.get("投信賣出股數")),
            "trust_net": _integer(row.get("投信買賣超股數")),
            "source": "TWSE 三大法人買賣超日報",
        }
    return None


def normalize_tpex(row: dict) -> dict:
    return {
        "symbol": str(row.get("SecuritiesCompanyCode", "")).strip(), "market": "TPEx",
        "trade_date": _parse_date(str(row["Date"])).isoformat(),
        "foreign_buy": _integer(row.get("Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Buy")),
        "foreign_sell": _integer(row.get(" Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Total Sell")),
        "foreign_net": _integer(row.get("Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference")),
        "trust_buy": _integer(row.get("SecuritiesInvestmentTrustCompanies-TotalBuy")),
        "trust_sell": _integer(row.get("SecuritiesInvestmentTrustCompanies-TotalSell")),
        "trust_net": _integer(row.get("SecuritiesInvestmentTrustCompanies-Difference")),
        "source": "TPEx 三大法人買賣明細",
    }


def sync_institutional_trades(database: Database, symbol: str) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError("找不到股票，請先同步上市、上櫃清單。")
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers) as client:
        if instrument["market"] == "TWSE":
            response = client.get("https://www.twse.com.tw/rwd/zh/fund/T86",
                                  params={"response": "json", "selectType": "ALLBUT0999"})
            response.raise_for_status()
            row = normalize_twse(response.json(), symbol)
        else:
            response = client.get("https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading")
            response.raise_for_status()
            source = next((item for item in response.json()
                           if str(item.get("SecuritiesCompanyCode", "")).strip() == symbol), None)
            row = normalize_tpex(source) if source else None
    if not row:
        raise LookupError("官方當日法人日報目前沒有這檔股票的資料。")
    return {"symbol": symbol, "trade_date": row["trade_date"],
            "rows_written": database.upsert_institutional_trades([row]), "status": "completed"}
