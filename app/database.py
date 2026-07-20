from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal

from app.domain import DailyPrice, Instrument


SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT NOT NULL,
    industry TEXT,
    currency TEXT NOT NULL DEFAULT 'TWD',
    website TEXT,
    chairman TEXT,
    established_date TEXT,
    listed_date TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market)
);
CREATE TABLE IF NOT EXISTS daily_prices (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    turnover REAL,
    transaction_count INTEGER,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol_date
ON daily_prices(symbol, trade_date DESC);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL,
    months_total INTEGER NOT NULL DEFAULT 0,
    months_completed INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS monthly_revenues (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    revenue_month TEXT NOT NULL,
    revenue REAL NOT NULL,
    previous_month_revenue REAL,
    previous_year_revenue REAL,
    mom_percent REAL,
    yoy_percent REAL,
    cumulative_revenue REAL,
    previous_year_cumulative_revenue REAL,
    cumulative_yoy_percent REAL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market, revenue_month)
);
CREATE INDEX IF NOT EXISTS idx_monthly_revenues_symbol_month
ON monthly_revenues(symbol, revenue_month DESC);
CREATE TABLE IF NOT EXISTS valuations (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    valuation_date TEXT NOT NULL,
    close_price REAL,
    pe_ratio REAL,
    pb_ratio REAL,
    dividend_yield REAL,
    dividend_per_share REAL,
    dividend_year TEXT,
    financial_period TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market, valuation_date)
);
CREATE INDEX IF NOT EXISTS idx_valuations_symbol_date
ON valuations(symbol, valuation_date DESC);
CREATE TABLE IF NOT EXISTS financial_snapshots (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter INTEGER NOT NULL,
    report_type TEXT NOT NULL,
    revenue REAL,
    gross_profit REAL,
    operating_income REAL,
    net_income REAL,
    eps REAL,
    current_assets REAL,
    total_assets REAL,
    current_liabilities REAL,
    total_liabilities REAL,
    equity REAL,
    book_value_per_share REAL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market, fiscal_year, fiscal_quarter)
);
CREATE INDEX IF NOT EXISTS idx_financial_snapshots_symbol_period
ON financial_snapshots(symbol, fiscal_year DESC, fiscal_quarter DESC);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market),
    FOREIGN KEY (symbol, market) REFERENCES instruments(symbol, market)
);
CREATE TABLE IF NOT EXISTS dividend_events (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    cash_dividend REAL,
    stock_dividend_ratio REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market, ex_date, event_type)
);
CREATE INDEX IF NOT EXISTS idx_dividend_events_symbol_date
ON dividend_events(symbol, ex_date DESC);
CREATE TABLE IF NOT EXISTS shareholder_distribution (
    symbol TEXT NOT NULL,
    data_date TEXT NOT NULL,
    holding_level INTEGER NOT NULL,
    holders INTEGER,
    shares INTEGER,
    percentage REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, data_date, holding_level)
);
CREATE INDEX IF NOT EXISTS idx_shareholder_distribution_symbol_date
ON shareholder_distribution(symbol, data_date DESC);
CREATE TABLE IF NOT EXISTS institutional_trades (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    foreign_buy INTEGER,
    foreign_sell INTEGER,
    foreign_net INTEGER,
    trust_buy INTEGER,
    trust_sell INTEGER,
    trust_net INTEGER,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_institutional_trades_symbol_date
ON institutional_trades(symbol, trade_date DESC);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(instruments)")}
            for name in ("website", "chairman", "established_date", "listed_date"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE instruments ADD COLUMN {name} TEXT")

    def upsert_instruments(self, rows: list[Instrument]) -> int:
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO instruments
                (symbol, market, name, industry, currency, website, chairman,
                 established_date, listed_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market) DO UPDATE SET
                name=excluded.name, industry=excluded.industry,
                currency=excluded.currency, website=excluded.website,
                chairman=excluded.chairman, established_date=excluded.established_date,
                listed_date=excluded.listed_date, updated_at=CURRENT_TIMESTAMP""",
                [(x.symbol, x.market, x.name, x.industry, x.currency, x.website,
                  x.chairman, x.established_date, x.listed_date) for x in rows],
            )
        return len(rows)

    def upsert_prices(self, rows: list[DailyPrice]) -> int:
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO daily_prices
                (symbol, market, trade_date, open, high, low, close, volume, turnover,
                 transaction_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, trade_date) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume, turnover=excluded.turnover,
                transaction_count=excluded.transaction_count, fetched_at=CURRENT_TIMESTAMP""",
                [
                    (x.symbol, x.market, x.trade_date.isoformat(), float(x.open), float(x.high),
                     float(x.low), float(x.close), x.volume,
                     float(x.turnover) if x.turnover is not None else None,
                     x.transaction_count)
                    for x in rows
                ],
            )
        return len(rows)

    def list_instruments(self, query: str | None = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM instruments"
        params: list[object] = []
        if query:
            sql += " WHERE symbol LIKE ? OR name LIKE ?"
            params.extend([f"%{query}%", f"%{query}%"])
        sql += " ORDER BY symbol LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def get_instrument(self, symbol: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM instruments WHERE symbol = ? ORDER BY market LIMIT 1", (symbol,)
            ).fetchone()
        return dict(row) if row else None

    def add_to_watchlist(self, symbol: str, market: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO watchlist(symbol, market) VALUES (?, ?)
                ON CONFLICT(symbol, market) DO NOTHING""",
                (symbol, market),
            )

    def remove_from_watchlist(self, symbol: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
            return cursor.rowcount

    def is_watched(self, symbol: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM watchlist WHERE symbol = ? LIMIT 1", (symbol,)
            ).fetchone()
        return row is not None

    def list_watchlist(self) -> list[dict]:
        sql = """
        SELECT w.symbol, w.market, w.added_at, i.name, i.industry,
               latest.trade_date, latest.close,
               previous.close AS previous_close,
               (SELECT MAX(h.close) FROM daily_prices h
                WHERE h.symbol=w.symbol AND h.market=w.market) AS all_time_high_close
        FROM watchlist w
        JOIN instruments i ON i.symbol=w.symbol AND i.market=w.market
        LEFT JOIN daily_prices latest ON latest.symbol=w.symbol AND latest.market=w.market
          AND latest.trade_date=(SELECT MAX(p.trade_date) FROM daily_prices p
                                 WHERE p.symbol=w.symbol AND p.market=w.market)
        LEFT JOIN daily_prices previous ON previous.symbol=w.symbol AND previous.market=w.market
          AND previous.trade_date=(SELECT MAX(p2.trade_date) FROM daily_prices p2
            WHERE p2.symbol=w.symbol AND p2.market=w.market
              AND p2.trade_date < latest.trade_date)
        ORDER BY w.added_at DESC
        """
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(sql)]
        for row in rows:
            close, previous, high = row["close"], row["previous_close"], row["all_time_high_close"]
            row["change_percent"] = close / previous - 1 if close and previous else None
            row["from_all_time_high"] = close / high - 1 if close and high else None
        return rows

    def list_popular_stocks(self, limit: int = 12) -> list[dict]:
        """Rank listed companies by latest-session turnover, a transparent attention proxy."""
        sql = """
        WITH market_dates AS (
            SELECT market, trade_date, COUNT(*) AS stocks_count
            FROM daily_prices GROUP BY market, trade_date
        ), ranked_dates AS (
            SELECT market, trade_date,
                   ROW_NUMBER() OVER (
                       PARTITION BY market ORDER BY stocks_count DESC, trade_date DESC
                   ) AS date_rank
            FROM market_dates
        ), latest_market AS (
            SELECT market, trade_date FROM ranked_dates WHERE date_rank=1
        )
        SELECT i.symbol, i.name, i.market, i.industry, p.trade_date, p.close,
               p.volume, p.turnover, p.transaction_count,
               CASE WHEN p.open > 0 THEN (p.close / p.open - 1) ELSE NULL END AS open_to_close
        FROM daily_prices p
        JOIN latest_market lm ON lm.market=p.market AND lm.trade_date=p.trade_date
        JOIN instruments i ON i.symbol=p.symbol AND i.market=p.market
        WHERE p.volume > 0 AND p.close > 0
        ORDER BY COALESCE(p.turnover, 0) DESC, p.volume DESC
        LIMIT ?
        """
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, (limit,))]

    def upsert_dividend_events(self, rows: list[dict]) -> int:
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO dividend_events
                (symbol, market, ex_date, event_type, cash_dividend, stock_dividend_ratio, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, ex_date, event_type) DO UPDATE SET
                cash_dividend=excluded.cash_dividend,
                stock_dividend_ratio=excluded.stock_dividend_ratio,
                source=excluded.source, fetched_at=CURRENT_TIMESTAMP""",
                [(
                    row["symbol"], row["market"], row["ex_date"], row["event_type"],
                    row.get("cash_dividend"), row.get("stock_dividend_ratio"), row["source"],
                ) for row in rows],
            )
        return len(rows)

    def get_dividend_events(self, symbol: str, limit: int = 20) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM dividend_events WHERE symbol=?
                ORDER BY ex_date DESC LIMIT ?""", (symbol, limit)
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_shareholder_distribution(self, rows: list[dict]) -> int:
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO shareholder_distribution
                (symbol, data_date, holding_level, holders, shares, percentage, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, data_date, holding_level) DO UPDATE SET
                holders=excluded.holders, shares=excluded.shares,
                percentage=excluded.percentage, source=excluded.source,
                fetched_at=CURRENT_TIMESTAMP""",
                [(
                    row["symbol"], row["data_date"], row["holding_level"],
                    row.get("holders"), row.get("shares"), row.get("percentage"),
                    row["source"],
                ) for row in rows],
            )
        return len(rows)

    def get_shareholder_distribution(self, symbol: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM shareholder_distribution
                WHERE symbol=? AND data_date=(
                    SELECT MAX(data_date) FROM shareholder_distribution WHERE symbol=?
                ) ORDER BY holding_level""",
                (symbol, symbol),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_institutional_trades(self, rows: list[dict]) -> int:
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO institutional_trades
                (symbol, market, trade_date, foreign_buy, foreign_sell, foreign_net,
                 trust_buy, trust_sell, trust_net, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, trade_date) DO UPDATE SET
                foreign_buy=excluded.foreign_buy, foreign_sell=excluded.foreign_sell,
                foreign_net=excluded.foreign_net, trust_buy=excluded.trust_buy,
                trust_sell=excluded.trust_sell, trust_net=excluded.trust_net,
                source=excluded.source, fetched_at=CURRENT_TIMESTAMP""",
                [(row["symbol"], row["market"], row["trade_date"], row["foreign_buy"],
                  row["foreign_sell"], row["foreign_net"], row["trust_buy"],
                  row["trust_sell"], row["trust_net"], row["source"]) for row in rows],
            )
        return len(rows)

    def get_institutional_trades(self, symbol: str, limit: int = 120) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM institutional_trades WHERE symbol=?
                ORDER BY trade_date DESC LIMIT ?""", (symbol, limit)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_prices(
        self,
        symbol: str,
        limit: int = 250,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        conditions = ["symbol = ?"]
        params: list[object] = [symbol]
        if start_date:
            conditions.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("trade_date <= ?")
            params.append(end_date)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM daily_prices WHERE {' AND '.join(conditions)}
                ORDER BY trade_date DESC LIMIT ?""",
                params,
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def create_sync_run(
        self, symbol: str, market: str, start_date: str, end_date: str, months_total: int
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO sync_runs
                (symbol, market, start_date, end_date, status, months_total)
                VALUES (?, ?, ?, ?, 'running', ?)""",
                (symbol, market, start_date, end_date, months_total),
            )
            return int(cursor.lastrowid)

    def update_sync_run(
        self,
        run_id: int,
        months_completed: int,
        rows_written: int,
        status: str = "running",
        error: str | None = None,
    ) -> None:
        finished = "CURRENT_TIMESTAMP" if status in {"completed", "failed"} else "NULL"
        with self.connect() as connection:
            connection.execute(
                f"""UPDATE sync_runs SET months_completed=?, rows_written=?, status=?, error=?,
                finished_at={finished} WHERE id=?""",
                (months_completed, rows_written, status, error, run_id),
            )

    def list_sync_runs(self, symbol: str | None = None, limit: int = 20) -> list[dict]:
        sql = "SELECT * FROM sync_runs"
        params: list[object] = []
        if symbol:
            sql += " WHERE symbol = ?"
            params.append(symbol)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params)]

    def upsert_monthly_revenue(self, row: dict) -> None:
        columns = (
            "symbol", "market", "revenue_month", "revenue", "previous_month_revenue",
            "previous_year_revenue", "mom_percent", "yoy_percent", "cumulative_revenue",
            "previous_year_cumulative_revenue", "cumulative_yoy_percent",
        )
        values = [float(row[key]) if isinstance(row[key], Decimal) else row[key] for key in columns]
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO monthly_revenues
                (symbol, market, revenue_month, revenue, previous_month_revenue,
                 previous_year_revenue, mom_percent, yoy_percent, cumulative_revenue,
                 previous_year_cumulative_revenue, cumulative_yoy_percent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, revenue_month) DO UPDATE SET
                revenue=excluded.revenue,
                previous_month_revenue=excluded.previous_month_revenue,
                previous_year_revenue=excluded.previous_year_revenue,
                mom_percent=excluded.mom_percent, yoy_percent=excluded.yoy_percent,
                cumulative_revenue=excluded.cumulative_revenue,
                previous_year_cumulative_revenue=excluded.previous_year_cumulative_revenue,
                cumulative_yoy_percent=excluded.cumulative_yoy_percent,
                fetched_at=CURRENT_TIMESTAMP""",
                values,
            )

    def get_monthly_revenues(self, symbol: str, limit: int = 60) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM monthly_revenues WHERE symbol=?
                ORDER BY revenue_month DESC LIMIT ?""",
                (symbol, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def upsert_valuation(self, row: dict) -> None:
        columns = (
            "symbol", "market", "valuation_date", "close_price", "pe_ratio", "pb_ratio",
            "dividend_yield", "dividend_per_share", "dividend_year", "financial_period",
        )
        values = []
        for key in columns:
            value = row.get(key)
            values.append(float(value) if isinstance(value, Decimal) else value)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO valuations
                (symbol, market, valuation_date, close_price, pe_ratio, pb_ratio,
                 dividend_yield, dividend_per_share, dividend_year, financial_period)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, valuation_date) DO UPDATE SET
                close_price=excluded.close_price, pe_ratio=excluded.pe_ratio,
                pb_ratio=excluded.pb_ratio, dividend_yield=excluded.dividend_yield,
                dividend_per_share=excluded.dividend_per_share,
                dividend_year=excluded.dividend_year,
                financial_period=excluded.financial_period, fetched_at=CURRENT_TIMESTAMP""",
                values,
            )

    def get_valuations(self, symbol: str, limit: int = 120) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM valuations WHERE symbol=?
                ORDER BY valuation_date DESC LIMIT ?""",
                (symbol, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def upsert_financials(self, row: dict) -> None:
        columns = (
            "symbol", "market", "fiscal_year", "fiscal_quarter", "report_type",
            "revenue", "gross_profit", "operating_income", "net_income", "eps",
            "current_assets", "total_assets", "current_liabilities", "total_liabilities",
            "equity", "book_value_per_share",
        )
        values = []
        for key in columns:
            value = row.get(key)
            values.append(float(value) if isinstance(value, Decimal) else value)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO financial_snapshots
                (symbol, market, fiscal_year, fiscal_quarter, report_type, revenue,
                 gross_profit, operating_income, net_income, eps, current_assets,
                 total_assets, current_liabilities, total_liabilities, equity,
                 book_value_per_share)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, fiscal_year, fiscal_quarter) DO UPDATE SET
                report_type=excluded.report_type, revenue=excluded.revenue,
                gross_profit=excluded.gross_profit, operating_income=excluded.operating_income,
                net_income=excluded.net_income, eps=excluded.eps,
                current_assets=excluded.current_assets, total_assets=excluded.total_assets,
                current_liabilities=excluded.current_liabilities,
                total_liabilities=excluded.total_liabilities, equity=excluded.equity,
                book_value_per_share=excluded.book_value_per_share,
                fetched_at=CURRENT_TIMESTAMP""",
                values,
            )

    def get_financials(self, symbol: str, limit: int = 20) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM financial_snapshots WHERE symbol=?
                ORDER BY fiscal_year DESC, fiscal_quarter DESC LIMIT ?""",
                (symbol, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_screening_universe(
        self, market: str | None = None, industry: str | None = None
    ) -> list[dict]:
        conditions = []
        params: list[object] = []
        if market:
            conditions.append("i.market = ?")
            params.append(market)
        if industry:
            conditions.append("i.industry LIKE ?")
            params.append(f"%{industry}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
        SELECT i.symbol, i.market, i.name, i.industry,
               p.close, p.volume, p.turnover, p.trade_date,
               r.yoy_percent,
               v.pe_ratio, v.pb_ratio, v.dividend_yield,
               f.fiscal_year, f.fiscal_quarter, f.report_type, f.revenue,
               f.gross_profit, f.operating_income, f.net_income, f.eps,
               f.current_assets, f.total_assets, f.current_liabilities,
               f.total_liabilities, f.equity, f.book_value_per_share
        FROM instruments i
        LEFT JOIN daily_prices p ON p.symbol=i.symbol AND p.market=i.market
          AND p.trade_date=(SELECT MAX(p2.trade_date) FROM daily_prices p2
                            WHERE p2.symbol=i.symbol AND p2.market=i.market)
        LEFT JOIN monthly_revenues r ON r.symbol=i.symbol AND r.market=i.market
          AND r.revenue_month=(SELECT MAX(r2.revenue_month) FROM monthly_revenues r2
                               WHERE r2.symbol=i.symbol AND r2.market=i.market)
        LEFT JOIN valuations v ON v.symbol=i.symbol AND v.market=i.market
          AND v.valuation_date=(SELECT MAX(v2.valuation_date) FROM valuations v2
                                WHERE v2.symbol=i.symbol AND v2.market=i.market)
        LEFT JOIN financial_snapshots f ON f.symbol=i.symbol AND f.market=i.market
          AND (f.fiscal_year * 10 + f.fiscal_quarter)=(
              SELECT MAX(f2.fiscal_year * 10 + f2.fiscal_quarter)
              FROM financial_snapshots f2
              WHERE f2.symbol=i.symbol AND f2.market=i.market)
        {where}
        """
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params)]
