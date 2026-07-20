import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.domain import DailyPrice, Instrument


DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "market_seed.json"
DEFAULT_ANALYSIS_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "analysis_seed.json"

ANALYSIS_SEED_COLUMNS = {
    "daily_prices": ("symbol", "market", "trade_date", "open", "high", "low", "close",
                     "volume", "turnover", "transaction_count"),
    "monthly_revenues": ("symbol", "market", "revenue_month", "revenue",
                         "previous_month_revenue", "previous_year_revenue", "mom_percent",
                         "yoy_percent", "cumulative_revenue",
                         "previous_year_cumulative_revenue", "cumulative_yoy_percent"),
    "valuations": ("symbol", "market", "valuation_date", "close_price", "pe_ratio",
                   "pb_ratio", "dividend_yield", "dividend_per_share", "dividend_year",
                   "financial_period"),
    "financial_snapshots": ("symbol", "market", "fiscal_year", "fiscal_quarter",
                            "report_type", "revenue", "gross_profit", "operating_income",
                            "net_income", "eps", "current_assets", "total_assets",
                            "current_liabilities", "total_liabilities", "equity",
                            "book_value_per_share"),
    "dividend_events": ("symbol", "market", "ex_date", "event_type", "cash_dividend",
                        "stock_dividend_ratio", "source"),
    "shareholder_distribution": ("symbol", "data_date", "holding_level", "holders",
                                 "shares", "percentage", "source"),
    "institutional_trades": ("symbol", "market", "trade_date", "foreign_buy",
                             "foreign_sell", "foreign_net", "trust_buy", "trust_sell",
                             "trust_net", "source"),
}


def load_market_seed(database: Database, path: Path = DEFAULT_SEED_PATH) -> dict[str, int]:
    """Load a public market snapshot so a fresh cloud database is immediately usable."""
    if not path.exists():
        return {"instruments": 0, "prices": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    instruments = [Instrument(**row) for row in payload.get("instruments", [])]
    prices = [
        DailyPrice(
            symbol=row["symbol"], market=row["market"],
            trade_date=date.fromisoformat(row["trade_date"]),
            open=Decimal(str(row["open"])), high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])), close=Decimal(str(row["close"])),
            volume=int(row["volume"]),
            turnover=Decimal(str(row["turnover"])) if row.get("turnover") is not None else None,
            transaction_count=row.get("transaction_count"),
        )
        for row in payload.get("prices", [])
    ]
    return {
        "instruments": database.upsert_instruments(instruments),
        "prices": database.upsert_prices(prices),
    }


def load_analysis_seed(
    database: Database, path: Path = DEFAULT_ANALYSIS_SEED_PATH
) -> dict[str, int]:
    """Load public analysis rows without overwriting newer data already synced in the cloud."""
    if not path.exists():
        return {table: 0 for table in ANALYSIS_SEED_COLUMNS}
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    with database.connect() as connection:
        for table, columns in ANALYSIS_SEED_COLUMNS.items():
            rows = payload.get(table, [])
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                ([row.get(column) for column in columns] for row in rows),
            )
            counts[table] = len(rows)
    return counts
