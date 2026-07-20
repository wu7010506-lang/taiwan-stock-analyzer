from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx

from app.config import settings
from app.database import Database
from app.providers import ProviderError


REPORT_TYPES = ("ci", "basi", "bd", "fh", "ins", "mim")


def _decimal(value: object) -> Decimal | None:
    text = str(value or "").replace(",", "").strip()
    if text in {"", "-", "--", "N/A"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ProviderError(f"財報數值格式異常：{value!r}") from exc


def _pick(row: dict, *names: str) -> object | None:
    return next((row[name] for name in names if name in row and row[name] != ""), None)


def _symbol(row: dict) -> str:
    return str(_pick(row, "公司代號", "SecuritiesCompanyCode") or "").strip()


def _fetch_rows(client: httpx.Client, url: str) -> list[dict]:
    try:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(f"官方財報 API 取得失敗：{exc}") from exc
    if not isinstance(payload, list):
        raise ProviderError("官方財報 API 回傳格式異常")
    return payload


def fetch_latest_financials(
    client: httpx.Client, symbol: str, market: str
) -> dict | None:
    if market == "TWSE":
        income_template = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_{}"
        balance_template = "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_{}"
    else:
        income_template = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_{}"
        balance_template = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_{}"

    income_row = None
    report_type = None
    for candidate in REPORT_TYPES:
        rows = _fetch_rows(client, income_template.format(candidate))
        income_row = next((row for row in rows if _symbol(row) == symbol), None)
        if income_row:
            report_type = candidate
            break
    if not income_row or not report_type:
        return None
    balance_type = report_type
    if market == "TPEx" and report_type in {"ins", "mim"}:
        balance_type = f"{report_type}A"
    balance_rows = _fetch_rows(client, balance_template.format(balance_type))
    balance_row = next((row for row in balance_rows if _symbol(row) == symbol), None)
    if not balance_row:
        return None

    return normalize_financial_rows(income_row, balance_row, report_type, market)


def normalize_financial_rows(
    income_row: dict, balance_row: dict, report_type: str, market: str
) -> dict:
    year = int(_pick(income_row, "年度", "Year") or 0)
    quarter = int(_pick(income_row, "季別", "Season") or 0)
    return {
        "symbol": _symbol(income_row),
        "market": market,
        "fiscal_year": year + 1911 if year < 1911 else year,
        "fiscal_quarter": quarter,
        "report_type": report_type,
        "revenue": _decimal(_pick(income_row, "營業收入", "收益")),
        "gross_profit": _decimal(
            _pick(income_row, "營業毛利（毛損）淨額", "營業毛利（毛損）")
        ),
        "operating_income": _decimal(_pick(income_row, "營業利益（損失）")),
        "net_income": _decimal(
            _pick(
                income_row,
                "淨利（淨損）歸屬於母公司業主",
                "本期淨利（淨損）",
                "本期稅後淨利（淨損）",
            )
        ),
        "eps": _decimal(_pick(income_row, "基本每股盈餘（元）", "基本每股盈餘")),
        "current_assets": _decimal(_pick(balance_row, "流動資產")),
        "total_assets": _decimal(_pick(balance_row, "資產總額", "資產總計")),
        "current_liabilities": _decimal(_pick(balance_row, "流動負債")),
        "total_liabilities": _decimal(_pick(balance_row, "負債總額", "負債總計")),
        "equity": _decimal(_pick(balance_row, "權益總額", "權益總計")),
        "book_value_per_share": _decimal(_pick(balance_row, "每股參考淨值")),
    }


def sync_financials(database: Database, symbol: str) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError("找不到股票代號；請先更新全市場清單")
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers, follow_redirects=True) as client:
        row = fetch_latest_financials(client, symbol, instrument["market"])
    if not row:
        raise LookupError("官方資料中找不到這檔股票的最新財報")
    database.upsert_financials(row)
    return {
        "symbol": symbol,
        "market": instrument["market"],
        "fiscal_year": row["fiscal_year"],
        "fiscal_quarter": row["fiscal_quarter"],
        "report_type": row["report_type"],
        "status": "completed",
    }


def analyze_financials(rows: list[dict]) -> dict:
    if not rows:
        return {}
    latest = rows[-1]

    def ratio(numerator: float | None, denominator: float | None) -> float | None:
        return numerator / denominator * 100 if numerator is not None and denominator else None

    revenue = latest["revenue"]
    net_income = latest["net_income"]
    equity = latest["equity"]
    quarter = latest["fiscal_quarter"]
    annualization = 4 / quarter if quarter else None
    annualized_roe = (
        ratio(net_income * annualization, equity)
        if net_income is not None and equity and annualization
        else None
    )
    if net_income is None:
        profitability = "資料不足"
    elif net_income > 0:
        profitability = "本期獲利"
    elif net_income < 0:
        profitability = "本期虧損"
    else:
        profitability = "本期損益兩平"
    return {
        "symbol": latest["symbol"],
        "fiscal_year": latest["fiscal_year"],
        "fiscal_quarter": quarter,
        "report_type": latest["report_type"],
        "eps": latest["eps"],
        "gross_margin_percent": ratio(latest["gross_profit"], revenue),
        "operating_margin_percent": ratio(latest["operating_income"], revenue),
        "net_margin_percent": ratio(net_income, revenue),
        "annualized_roe_percent": annualized_roe,
        "debt_ratio_percent": ratio(latest["total_liabilities"], latest["total_assets"]),
        "current_ratio_percent": ratio(latest["current_assets"], latest["current_liabilities"]),
        "book_value_per_share": latest["book_value_per_share"],
        "profitability_status": profitability,
        "observations": len(rows),
    }
