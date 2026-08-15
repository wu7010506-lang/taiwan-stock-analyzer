from __future__ import annotations

from collections import defaultdict
from datetime import date

import httpx

from app.config import settings
from app.database import Database
from app.providers import ProviderError


FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

INCOME_TYPES = {
    "Revenue": "revenue", "GrossProfit": "gross_profit",
    "OperatingIncome": "operating_income", "IncomeAfterTaxes": "net_income",
    "EPS": "eps", "InterestExpense": "interest_expense",
}
BALANCE_TYPES = {
    "CurrentAssets": "current_assets", "TotalAssets": "total_assets",
    "CurrentLiabilities": "current_liabilities", "Liabilities": "total_liabilities",
    "Equity": "equity", "CashAndCashEquivalents": "cash_and_equivalents",
    "Inventories": "inventory", "PropertyPlantAndEquipment": "property_plant_equipment",
    "CapitalStock": "share_capital",
}
CASH_TYPES = {
    "CashFlowsFromOperatingActivities": "operating_cash_flow",
    "NetCashInflowFromOperatingActivities": "operating_cash_flow",
    "PropertyAndPlantAndEquipment": "capital_expenditure",
}


def _fetch(client: httpx.Client, dataset: str, symbol: str, start_date: str) -> list[dict]:
    params = {"dataset": dataset, "data_id": symbol, "start_date": start_date}
    if settings.finmind_token:
        params["token"] = settings.finmind_token
    try:
        response = client.get(FINMIND_URL, params=params)
        if response.status_code == 402:
            raise ProviderError(
                "FinMind public API quota is temporarily exhausted; retry after the quota "
                "resets or configure FINMIND_TOKEN"
            )
        response.raise_for_status()
        payload = response.json()
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(f"FinMind {dataset} request failed: {exc}") from exc
    if payload.get("status") != 200 or not isinstance(payload.get("data"), list):
        raise ProviderError(payload.get("msg") or f"FinMind {dataset} returned invalid data")
    return payload["data"]


def _pivot(rows: list[dict], mapping: dict[str, str]) -> dict[str, dict]:
    periods: dict[str, dict] = defaultdict(dict)
    for item in rows:
        field = mapping.get(str(item.get("type", "")))
        statement_date = str(item.get("date", ""))
        if not field or not statement_date:
            continue
        try:
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
        # Prefer the primary OCF taxonomy when both aliases occur.
        if field not in periods[statement_date] or item.get("type") == "CashFlowsFromOperatingActivities":
            periods[statement_date][field] = value
    return periods


def normalize_finmind_history(
    symbol: str, market: str, income: list[dict], balance: list[dict], cash: list[dict]
) -> list[dict]:
    income_by_date = _pivot(income, INCOME_TYPES)
    balance_by_date = _pivot(balance, BALANCE_TYPES)
    cash_by_date = _pivot(cash, CASH_TYPES)
    rows = []
    for statement_date in sorted(set(income_by_date) | set(balance_by_date) | set(cash_by_date)):
        parsed = date.fromisoformat(statement_date)
        if parsed.month not in {3, 6, 9, 12}:
            continue
        values = {**income_by_date.get(statement_date, {}),
                  **balance_by_date.get(statement_date, {}),
                  **cash_by_date.get(statement_date, {})}
        capex = values.get("capital_expenditure")
        if capex is not None:
            values["capital_expenditure"] = abs(capex)
        ocf = values.get("operating_cash_flow")
        if ocf is not None and capex is not None:
            values["free_cash_flow"] = ocf - abs(capex)
        rows.append({
            "symbol": symbol, "market": market, "fiscal_year": parsed.year,
            "fiscal_quarter": parsed.month // 3, "report_type": "finmind",
            "statement_date": statement_date, "source": "FinMind / MOPS", **values,
        })
    return rows


def normalize_finmind_dividends(symbol: str, market: str, rows: list[dict]) -> list[dict]:
    result = []
    for item in rows:
        ex_date = str(item.get("CashExDividendTradingDate") or "")[:10]
        if not ex_date:
            continue
        cash = float(item.get("CashEarningsDistribution") or 0) + float(
            item.get("CashStatutorySurplus") or 0
        )
        stock = float(item.get("StockEarningsDistribution") or 0) + float(
            item.get("StockStatutorySurplus") or 0
        )
        result.append({"symbol": symbol, "market": market, "ex_date": ex_date,
                       "event_type": "cash/stock dividend", "cash_dividend": cash,
                       "stock_dividend_ratio": stock, "source": "FinMind / MOPS"})
    return result


def sync_historical_fundamentals(database: Database, symbol: str, years: int = 5) -> dict:
    instrument = database.get_instrument(symbol)
    if not instrument:
        raise LookupError(f"Stock {symbol} was not found")
    start_date = date(date.today().year - years, 1, 1).isoformat()
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers,
                      follow_redirects=True) as client:
        income = _fetch(client, "TaiwanStockFinancialStatements", symbol, start_date)
        balance = _fetch(client, "TaiwanStockBalanceSheet", symbol, start_date)
        cash = _fetch(client, "TaiwanStockCashFlowsStatement", symbol, start_date)
        dividends = _fetch(client, "TaiwanStockDividend", symbol, start_date)
    financial_rows = normalize_finmind_history(
        symbol, instrument["market"], income, balance, cash
    )
    for row in financial_rows:
        database.upsert_financials(row)
    dividend_rows = normalize_finmind_dividends(symbol, instrument["market"], dividends)
    database.upsert_dividend_events(dividend_rows)
    return {"symbol": symbol, "market": instrument["market"], "years_requested": years,
            "financial_rows_written": len(financial_rows),
            "dividend_rows_written": len(dividend_rows),
            "coverage": database.get_fundamentals_coverage(symbol), "status": "completed"}
