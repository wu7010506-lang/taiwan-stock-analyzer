from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.domain import DailyPrice, Instrument


class ProviderError(RuntimeError):
    pass


def _number(value: Any) -> Decimal:
    text = str(value or "0").replace(",", "").strip()
    if text in {"", "--", "---", "-"}:
        return Decimal(0)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ProviderError(f"無法解析數值：{value!r}") from exc


def _integer(value: Any) -> int:
    return int(_number(value))


def _parse_date(value: str) -> date:
    text = value.strip().replace("/", "-")
    if text.isdigit() and len(text) == 7:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:7]))
    if text.isdigit() and len(text) == 8:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 3:
        text = f"{int(parts[0]) + 1911:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return datetime.strptime(text, "%Y-%m-%d").date()


class MarketProvider(ABC):
    market: str

    def __init__(self, client: httpx.Client):
        self.client = client

    def _get(self, url: str) -> list[dict[str, Any]]:
        try:
            response = self.client.get(url, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"{self.market} API 取得失敗：{exc}") from exc
        if not isinstance(payload, list):
            raise ProviderError(f"{self.market} API 回傳格式異常")
        return payload

    @abstractmethod
    def fetch_instruments(self) -> list[Instrument]: ...

    @abstractmethod
    def fetch_latest_prices(self) -> list[DailyPrice]: ...


class TwseProvider(MarketProvider):
    market = "TWSE"
    base_url = "https://openapi.twse.com.tw/v1"

    def fetch_instruments(self) -> list[Instrument]:
        rows = self._get(f"{self.base_url}/opendata/t187ap03_L")
        return [
            Instrument(
                symbol=str(row.get("公司代號", "")).strip(),
                name=str(row.get("公司簡稱") or row.get("公司名稱") or "").strip(),
                market=self.market,
                industry=str(row.get("產業別", "")).strip() or None,
                website=str(row.get("網址", "")).strip() or None,
                chairman=str(row.get("董事長", "")).strip() or None,
                established_date=str(row.get("成立日期", "")).strip() or None,
                listed_date=str(row.get("上市日期", "")).strip() or None,
            )
            for row in rows
            if row.get("公司代號")
        ]

    def fetch_latest_prices(self) -> list[DailyPrice]:
        rows = self._get(f"{self.base_url}/exchangeReport/STOCK_DAY_ALL")
        result = []
        for row in rows:
            symbol = str(row.get("Code", "")).strip()
            if not symbol:
                continue
            result.append(
                DailyPrice(
                    symbol=symbol,
                    market=self.market,
                    trade_date=_parse_date(str(row["Date"])),
                    open=_number(row.get("OpeningPrice")),
                    high=_number(row.get("HighestPrice")),
                    low=_number(row.get("LowestPrice")),
                    close=_number(row.get("ClosingPrice")),
                    volume=_integer(row.get("TradeVolume")),
                    turnover=_number(row.get("TradeValue")),
                    transaction_count=_integer(row.get("Transaction")),
                )
            )
        return result

    def fetch_history_month(self, symbol: str, month: date) -> list[DailyPrice]:
        url = (
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
            f"?date={month:%Y%m}01&stockNo={symbol}&response=json"
        )
        try:
            response = self.client.get(url, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"TWSE {symbol} {month:%Y-%m} 歷史行情取得失敗：{exc}") from exc
        if payload.get("stat") != "OK":
            return []
        return [
            DailyPrice(
                symbol=symbol,
                market=self.market,
                trade_date=_parse_date(row[0]),
                volume=_integer(row[1]),
                turnover=_number(row[2]),
                open=_number(row[3]),
                high=_number(row[4]),
                low=_number(row[5]),
                close=_number(row[6]),
                transaction_count=_integer(row[8]),
            )
            for row in payload.get("data", [])
            if len(row) >= 9
        ]


class TpexProvider(MarketProvider):
    market = "TPEx"
    base_url = "https://www.tpex.org.tw/openapi/v1"

    def fetch_instruments(self) -> list[Instrument]:
        rows = self._get(f"{self.base_url}/mopsfin_t187ap03_O")
        return [
            Instrument(
                symbol=str(row.get("SecuritiesCompanyCode") or row.get("公司代號") or "").strip(),
                name=str(
                    row.get("CompanyAbbreviation")
                    or row.get("CompanyName")
                    or row.get("公司簡稱")
                    or row.get("公司名稱")
                    or ""
                ).strip(),
                market=self.market,
                industry=str(
                    row.get("SecuritiesIndustryCode") or row.get("產業別") or ""
                ).strip() or None,
                website=str(row.get("WebAddress") or row.get("網址") or "").strip() or None,
                chairman=str(row.get("Chairman") or row.get("董事長") or "").strip() or None,
                established_date=str(row.get("DateOfEstablishment") or row.get("成立日期") or "").strip() or None,
                listed_date=str(row.get("DateOfListing") or row.get("上櫃日期") or "").strip() or None,
            )
            for row in rows
            if row.get("SecuritiesCompanyCode") or row.get("公司代號")
        ]

    def fetch_latest_prices(self) -> list[DailyPrice]:
        rows = self._get(f"{self.base_url}/tpex_mainboard_daily_close_quotes")
        aliases = {
            "symbol": ("SecuritiesCompanyCode", "證券代號", "股票代號"),
            "date": ("Date", "資料日期", "日期"),
            "open": ("Open", "開盤價"),
            "high": ("High", "最高價"),
            "low": ("Low", "最低價"),
            "close": ("Close", "收盤價"),
            "volume": ("TradingShares", "成交股數"),
            "turnover": ("TransactionAmount", "成交金額"),
            "count": ("TransactionNumber", "成交筆數"),
        }

        def pick(row: dict[str, Any], key: str) -> Any:
            return next((row[name] for name in aliases[key] if name in row), None)

        result = []
        for row in rows:
            symbol = str(pick(row, "symbol") or "").strip()
            raw_date = pick(row, "date")
            if not symbol or not raw_date:
                continue
            result.append(
                DailyPrice(
                    symbol=symbol,
                    market=self.market,
                    trade_date=_parse_date(str(raw_date)),
                    open=_number(pick(row, "open")),
                    high=_number(pick(row, "high")),
                    low=_number(pick(row, "low")),
                    close=_number(pick(row, "close")),
                    volume=_integer(pick(row, "volume")),
                    turnover=_number(pick(row, "turnover")),
                    transaction_count=_integer(pick(row, "count")),
                )
            )
        return result

    def fetch_history_month(self, symbol: str, month: date) -> list[DailyPrice]:
        url = (
            "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
            f"?code={symbol}&date={month:%Y/%m}/01&response=json"
        )
        try:
            response = self.client.get(url, follow_redirects=True)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"TPEx {symbol} {month:%Y-%m} 歷史行情取得失敗：{exc}") from exc
        tables = payload.get("tables") or []
        rows = tables[0].get("data", []) if tables else []
        return [
            DailyPrice(
                symbol=symbol,
                market=self.market,
                trade_date=_parse_date(row[0]),
                # TPEx 歷史查詢頁的成交量與成交金額單位皆為「仟」。
                volume=_integer(row[1]) * 1000,
                turnover=_number(row[2]) * 1000,
                open=_number(row[3]),
                high=_number(row[4]),
                low=_number(row[5]),
                close=_number(row[6]),
                transaction_count=_integer(row[8]),
            )
            for row in rows
            if len(row) >= 9
        ]
