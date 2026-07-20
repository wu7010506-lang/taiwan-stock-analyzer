from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    market: str
    industry: str | None = None
    currency: str = "TWD"
    website: str | None = None
    chairman: str | None = None
    established_date: str | None = None
    listed_date: str | None = None


@dataclass(frozen=True)
class DailyPrice:
    symbol: str
    market: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal | None = None
    transaction_count: int | None = None
