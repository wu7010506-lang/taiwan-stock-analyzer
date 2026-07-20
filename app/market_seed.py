import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.database import Database
from app.domain import DailyPrice, Instrument


DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "market_seed.json"


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
