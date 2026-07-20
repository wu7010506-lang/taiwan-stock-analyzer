from __future__ import annotations

import csv
import io
from datetime import date
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from app.analysis import analyze
from app.config import settings
from app.database import Database
from app.financials import (
    REPORT_TYPES,
    _fetch_rows,
    _symbol,
    analyze_financials,
    normalize_financial_rows,
)
from app.providers import _parse_date
from app.revenue import _decimal as revenue_decimal
from app.valuation import _decimal as valuation_decimal
from app.themes import THEME_SYMBOLS, stock_themes


class ScreenerFilters(BaseModel):
    market: Literal["TWSE", "TPEx"] | None = None
    industry: str | None = None
    min_revenue_yoy: float | None = None
    min_gross_margin: float | None = None
    min_roe: float | None = None
    max_debt_ratio: float | None = None
    max_pe: float | None = None
    min_dividend_yield: float | None = None
    popular_only: bool = True
    ai_theme: bool = False
    defense_drone_theme: bool = False
    ic_design_theme: bool = False
    above_sma60: bool | None = None
    min_rsi: float | None = None
    max_rsi: float | None = None
    sort_by: Literal[
        "symbol", "revenue_yoy", "roe", "pe", "dividend_yield", "turnover", "completeness"
    ] = "completeness"
    descending: bool = True
    limit: int = Field(100, ge=1, le=3000)


def _roc_month(value: str) -> str:
    text = value.strip()
    if len(text) == 5:
        return f"{int(text[:3]) + 1911:04d}-{int(text[3:]):02d}"
    if len(text) == 6:
        return f"{int(text[:3]) + 1911:04d}-{int(text[3:]):02d}"
    raise ValueError(f"無法解析資料年月：{value}")


def _sync_revenues(database: Database, client: httpx.Client) -> int:
    sources = (
        ("TWSE", "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"),
        ("TPEx", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"),
    )
    count = 0
    for market, url in sources:
        for row in _fetch_rows(client, url):
            symbol = str(row.get("公司代號", "")).strip()
            revenue = revenue_decimal(row.get("營業收入-當月營收", ""))
            if not symbol or revenue is None:
                continue
            database.upsert_monthly_revenue({
                "symbol": symbol,
                "market": market,
                "revenue_month": _roc_month(str(row["資料年月"])),
                "revenue": revenue,
                "previous_month_revenue": revenue_decimal(row.get("營業收入-上月營收", "")),
                "previous_year_revenue": revenue_decimal(row.get("營業收入-去年當月營收", "")),
                "mom_percent": revenue_decimal(row.get("營業收入-上月比較增減(%)", "")),
                "yoy_percent": revenue_decimal(row.get("營業收入-去年同月增減(%)", "")),
                "cumulative_revenue": revenue_decimal(row.get("累計營業收入-當月累計營收", "")),
                "previous_year_cumulative_revenue": revenue_decimal(row.get("累計營業收入-去年累計營收", "")),
                "cumulative_yoy_percent": revenue_decimal(row.get("累計營業收入-前期比較增減(%)", "")),
            })
            count += 1
    return count


def _sync_valuations(database: Database, client: httpx.Client) -> int:
    sources = (
        ("TWSE", "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"),
        ("TPEx", "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"),
    )
    count = 0
    for market, url in sources:
        for row in _fetch_rows(client, url):
            if market == "TWSE":
                symbol = str(row.get("Code", "")).strip()
                normalized = {
                    "valuation_date": _parse_date(str(row.get("Date"))).strftime("%Y%m%d"),
                    "pe_ratio": valuation_decimal(row.get("PEratio")),
                    "pb_ratio": valuation_decimal(row.get("PBratio")),
                    "dividend_yield": valuation_decimal(row.get("DividendYield")),
                }
            else:
                symbol = str(row.get("SecuritiesCompanyCode", "")).strip()
                normalized = {
                    "valuation_date": _parse_date(str(row.get("Date"))).strftime("%Y%m%d"),
                    "pe_ratio": valuation_decimal(row.get("PriceEarningRatio")),
                    "pb_ratio": valuation_decimal(row.get("PriceBookRatio")),
                    "dividend_yield": valuation_decimal(row.get("YieldRatio")),
                    "dividend_per_share": valuation_decimal(row.get("DividendPerShare")),
                }
            if not symbol:
                continue
            database.upsert_valuation({"symbol": symbol, "market": market, **normalized})
            count += 1
    return count


def _sync_financials(database: Database, client: httpx.Client) -> int:
    count = 0
    for market in ("TWSE", "TPEx"):
        if market == "TWSE":
            income_template = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_{}"
            balance_template = "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_{}"
        else:
            income_template = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_{}"
            balance_template = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_{}"
        for report_type in REPORT_TYPES:
            income_rows = _fetch_rows(client, income_template.format(report_type))
            balance_type = (
                f"{report_type}A"
                if market == "TPEx" and report_type in {"ins", "mim"}
                else report_type
            )
            balance_rows = _fetch_rows(client, balance_template.format(balance_type))
            balances = {_symbol(row): row for row in balance_rows}
            for income_row in income_rows:
                symbol = _symbol(income_row)
                if symbol and symbol in balances:
                    database.upsert_financials(
                        normalize_financial_rows(
                            income_row, balances[symbol], report_type, market
                        )
                    )
                    count += 1
    return count


def sync_screening_universe(database: Database) -> dict:
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=settings.http_timeout_seconds, headers=headers, follow_redirects=True) as client:
        revenues = _sync_revenues(database, client)
        valuations = _sync_valuations(database, client)
        financials = _sync_financials(database, client)
    return {
        "as_of": date.today(),
        "revenues": revenues,
        "valuations": valuations,
        "financials": financials,
        "status": "completed",
    }


def screen_stocks(database: Database, filters: ScreenerFilters) -> list[dict]:
    base_rows = database.get_screening_universe(filters.market, filters.industry)
    popular = {row["symbol"]: index + 1 for index, row in enumerate(database.list_popular_stocks(100))}
    results = []
    technical_requested = (
        filters.above_sma60 is not None
        or filters.min_rsi is not None
        or filters.max_rsi is not None
    )
    selected_themes = [
        key for key, enabled in (
            ("ai", filters.ai_theme), ("defense_drone", filters.defense_drone_theme),
            ("ic_design", filters.ic_design_theme),
        ) if enabled
    ]
    for row in base_rows:
        financial = analyze_financials([row]) if row.get("fiscal_year") else {}
        item = {
            "symbol": row["symbol"],
            "name": row["name"],
            "market": row["market"],
            "industry": row["industry"],
            "close": row["close"],
            "volume": row["volume"],
            "turnover": row["turnover"],
            "trade_date": row["trade_date"],
            "popular_rank": popular.get(row["symbol"]),
            "themes": stock_themes(row["symbol"]),
            "revenue_yoy": row["yoy_percent"],
            "gross_margin": financial.get("gross_margin_percent"),
            "roe": financial.get("annualized_roe_percent"),
            "debt_ratio": financial.get("debt_ratio_percent"),
            "pe": row["pe_ratio"],
            "pb": row["pb_ratio"],
            "dividend_yield": row["dividend_yield"],
            "sma60": None,
            "rsi14": None,
        }
        if technical_requested:
            technical = analyze(database.get_prices(row["symbol"], 120))
            item["sma60"] = technical.get("sma_60")
            item["rsi14"] = technical.get("rsi_14")
        completeness_fields = (
            "revenue_yoy", "gross_margin", "roe", "debt_ratio", "pe", "pb",
            "dividend_yield",
        )
        item["completeness"] = round(
            sum(item[key] is not None for key in completeness_fields)
            / len(completeness_fields)
            * 100
        )
        checks = (
            (filters.min_revenue_yoy, item["revenue_yoy"], lambda value, threshold: value >= threshold),
            (filters.min_gross_margin, item["gross_margin"], lambda value, threshold: value >= threshold),
            (filters.min_roe, item["roe"], lambda value, threshold: value >= threshold),
            (filters.max_debt_ratio, item["debt_ratio"], lambda value, threshold: value <= threshold),
            (filters.max_pe, item["pe"], lambda value, threshold: value <= threshold),
            (filters.min_dividend_yield, item["dividend_yield"], lambda value, threshold: value >= threshold),
            (filters.min_rsi, item["rsi14"], lambda value, threshold: value >= threshold),
            (filters.max_rsi, item["rsi14"], lambda value, threshold: value <= threshold),
        )
        if any(threshold is not None and (value is None or not check(value, threshold)) for threshold, value, check in checks):
            continue
        if filters.above_sma60 is not None:
            above = item["close"] is not None and item["sma60"] is not None and item["close"] > item["sma60"]
            if above != filters.above_sma60:
                continue
        if filters.popular_only and item["popular_rank"] is None:
            continue
        if selected_themes and not any(row["symbol"] in THEME_SYMBOLS[key] for key in selected_themes):
            continue
        results.append(item)

    sort_keys = {
        "symbol": "symbol", "revenue_yoy": "revenue_yoy", "roe": "roe",
        "pe": "pe", "dividend_yield": "dividend_yield", "turnover": "turnover",
        "completeness": "completeness",
    }
    key = sort_keys[filters.sort_by]
    results.sort(
        key=lambda item: (item[key] is not None, item[key] if item[key] is not None else 0),
        reverse=filters.descending,
    )
    return results[: filters.limit]


def screening_csv(rows: list[dict]) -> str:
    output = io.StringIO()
    output.write("\ufeff")
    columns = [
        "symbol", "name", "market", "industry", "close", "revenue_yoy",
        "gross_margin", "roe", "debt_ratio", "pe", "pb", "dividend_yield",
        "volume", "turnover", "trade_date", "popular_rank", "themes", "sma60", "rsi14", "completeness",
    ]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
