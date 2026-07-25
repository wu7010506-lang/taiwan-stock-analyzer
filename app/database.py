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
    operating_cash_flow REAL,
    capital_expenditure REAL,
    free_cash_flow REAL,
    cash_and_equivalents REAL,
    inventory REAL,
    property_plant_equipment REAL,
    share_capital REAL,
    interest_expense REAL,
    statement_date TEXT,
    source TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market, fiscal_year, fiscal_quarter)
);
CREATE INDEX IF NOT EXISTS idx_financial_snapshots_symbol_period
ON financial_snapshots(symbol, fiscal_year DESC, fiscal_quarter DESC);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    average_cost REAL,
    shares INTEGER,
    purchase_date TEXT,
    stop_loss REAL,
    target_price REAL,
    investment_horizon TEXT,
    notes TEXT,
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
CREATE TABLE IF NOT EXISTS fundamental_sync_queue (
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    years_requested INTEGER NOT NULL DEFAULT 5,
    financial_rows INTEGER NOT NULL DEFAULT 0,
    dividend_rows INTEGER NOT NULL DEFAULT 0,
    price_status TEXT NOT NULL DEFAULT 'pending',
    price_rows INTEGER NOT NULL DEFAULT 0,
    price_error TEXT,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market)
);
CREATE INDEX IF NOT EXISTS idx_fundamental_sync_queue_status
ON fundamental_sync_queue(status, priority);
CREATE TABLE IF NOT EXISTS daily_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    steps_json TEXT,
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS market_index_snapshots (
    trade_date TEXT PRIMARY KEY,
    close REAL NOT NULL,
    market_score REAL,
    regime TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS recommendation_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    profile TEXT NOT NULL,
    model_version TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    decision TEXT,
    close REAL NOT NULL,
    market_close REAL,
    market_score REAL,
    market_regime TEXT,
    industry TEXT,
    industry_category TEXT,
    factors_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    risks_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, symbol, market, profile)
);
CREATE INDEX IF NOT EXISTS idx_recommendation_snapshots_profile_date
ON recommendation_snapshots(profile, snapshot_date DESC, rank);
CREATE TABLE IF NOT EXISTS analysis_sync_state (
    symbol TEXT NOT NULL,
    dataset TEXT NOT NULL,
    last_attempt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (symbol, dataset)
);
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
            financial_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(financial_snapshots)")
            }
            additions = {
                "operating_cash_flow": "REAL", "capital_expenditure": "REAL",
                "free_cash_flow": "REAL", "cash_and_equivalents": "REAL",
                "inventory": "REAL", "property_plant_equipment": "REAL",
                "share_capital": "REAL", "interest_expense": "REAL",
                "statement_date": "TEXT", "source": "TEXT",
            }
            for name, sql_type in additions.items():
                if name not in financial_columns:
                    connection.execute(
                        f"ALTER TABLE financial_snapshots ADD COLUMN {name} {sql_type}"
                    )
            connection.execute(
                """UPDATE fundamental_sync_queue
                   SET error='FinMind public API quota is temporarily exhausted; retry later'
                   WHERE error LIKE '%402 Payment Required%'"""
            )
            queue_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(fundamental_sync_queue)")
            }
            for name, definition in {
                "price_status": "TEXT NOT NULL DEFAULT 'pending'",
                "price_rows": "INTEGER NOT NULL DEFAULT 0", "price_error": "TEXT",
            }.items():
                if name not in queue_columns:
                    connection.execute(
                        f"ALTER TABLE fundamental_sync_queue ADD COLUMN {name} {definition}"
                    )
            watchlist_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(watchlist)")
            }
            for name, definition in {
                "average_cost": "REAL", "shares": "INTEGER", "purchase_date": "TEXT",
                "stop_loss": "REAL", "target_price": "REAL",
                "investment_horizon": "TEXT", "notes": "TEXT",
            }.items():
                if name not in watchlist_columns:
                    connection.execute(f"ALTER TABLE watchlist ADD COLUMN {name} {definition}")

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
        SELECT w.symbol, w.market, w.added_at, w.average_cost, w.shares,
               w.purchase_date, w.stop_loss, w.target_price, w.investment_horizon,
               w.notes, i.name, i.industry,
               latest.trade_date, latest.close,
               previous.close AS previous_close,
               (SELECT MAX(mp.trade_date) FROM daily_prices mp WHERE mp.close > 0)
                 AS market_latest_date,
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
            row["quote_is_current"] = bool(
                row["trade_date"] and row["market_latest_date"]
                and row["trade_date"] >= row["market_latest_date"]
            )
            row["from_all_time_high"] = close / high - 1 if close and high else None
            shares = int(row["shares"] or 0)
            cost = row["average_cost"]
            row["is_held"] = bool(shares > 0 and cost and cost > 0)
            row["cost_basis"] = float(cost) * shares if row["is_held"] else None
            row["market_value"] = float(close) * shares if row["is_held"] and close else None
            row["unrealized_profit"] = (row["market_value"] - row["cost_basis"]
                                        if row["market_value"] is not None else None)
            row["unrealized_return"] = (row["unrealized_profit"] / row["cost_basis"]
                                        if row["unrealized_profit"] is not None
                                        and row["cost_basis"] else None)
            row["stop_triggered"] = bool(row["stop_loss"] and close
                                         and float(close) <= float(row["stop_loss"]))
            row["target_reached"] = bool(row["target_price"] and close
                                         and float(close) >= float(row["target_price"]))
        return rows

    def update_watchlist_position(self, symbol: str, row: dict) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE watchlist SET average_cost=?, shares=?, purchase_date=?,
                          stop_loss=?, target_price=?, investment_horizon=?, notes=?
                   WHERE symbol=?""",
                (row.get("average_cost"), row.get("shares"), row.get("purchase_date"),
                 row.get("stop_loss"), row.get("target_price"),
                 row.get("investment_horizon"), row.get("notes"), symbol),
            )
        return cursor.rowcount > 0

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

    def prepare_fundamental_sync_queue(self, rows: list[dict], years: int) -> int:
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO fundamental_sync_queue
                   (symbol, market, priority, years_requested) VALUES (?, ?, ?, ?)
                   ON CONFLICT(symbol, market) DO UPDATE SET
                     priority=excluded.priority, years_requested=excluded.years_requested,
                     updated_at=CURRENT_TIMESTAMP""",
                [(row["symbol"], row["market"], index, years)
                for index, row in enumerate(rows, 1)],
            )
            connection.execute(
                """UPDATE fundamental_sync_queue AS q
                   SET status='completed',
                       financial_rows=(SELECT COUNT(*) FROM financial_snapshots f
                                       WHERE f.symbol=q.symbol AND f.market=q.market
                                         AND f.statement_date IS NOT NULL),
                       dividend_rows=(SELECT COUNT(*) FROM dividend_events d
                                      WHERE d.symbol=q.symbol AND d.market=q.market),
                       updated_at=CURRENT_TIMESTAMP
                   WHERE status='pending'
                     AND (SELECT COUNT(DISTINCT f.fiscal_year)
                          FROM financial_snapshots f
                          WHERE f.symbol=q.symbol AND f.market=q.market
                            AND f.statement_date IS NOT NULL) >= 5
                     AND (SELECT COUNT(*) FROM financial_snapshots f
                          WHERE f.symbol=q.symbol AND f.market=q.market
                            AND f.operating_cash_flow IS NOT NULL) >= 12"""
            )
        return len(rows)

    def reset_failed_fundamental_syncs(self) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE fundamental_sync_queue SET status='pending', error=NULL,
                          updated_at=CURRENT_TIMESTAMP WHERE status='failed'"""
            )
        return cursor.rowcount

    def claim_fundamental_sync_batch(self, limit: int) -> list[dict]:
        with self.connect() as connection:
            connection.execute(
                """UPDATE fundamental_sync_queue SET status='pending'
                   WHERE status='running'
                     AND datetime(updated_at) < datetime('now', '-30 minutes')"""
            )
            rows = [dict(row) for row in connection.execute(
                """SELECT * FROM fundamental_sync_queue WHERE status='pending'
                   ORDER BY priority LIMIT ?""", (limit,)
            )]
            connection.executemany(
                """UPDATE fundamental_sync_queue SET status='running', attempts=attempts+1,
                          started_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                   WHERE symbol=? AND market=?""",
                [(row["symbol"], row["market"]) for row in rows],
            )
        return rows

    def finish_fundamental_sync(self, symbol: str, market: str, result: dict | None = None,
                                error: str | None = None) -> None:
        result = result or {}
        with self.connect() as connection:
            connection.execute(
                """UPDATE fundamental_sync_queue SET status=?, financial_rows=?,
                          dividend_rows=?, error=?, finished_at=CURRENT_TIMESTAMP,
                          updated_at=CURRENT_TIMESTAMP WHERE symbol=? AND market=?""",
                ("failed" if error else "completed", result.get("financial_rows_written", 0),
                 result.get("dividend_rows_written", 0), error, symbol, market),
            )

    def get_fundamental_sync_progress(self, target_limit: int | None = None) -> dict:
        condition = "WHERE priority <= ?" if target_limit else ""
        params = (target_limit,) if target_limit else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT status, COUNT(*) AS count FROM fundamental_sync_queue {condition} GROUP BY status",
                params,
            ).fetchall()
            failure_where = condition + (" AND" if condition else "WHERE")
            failures = [dict(row) for row in connection.execute(
                f"""SELECT symbol, market, error, attempts FROM fundamental_sync_queue
                    {failure_where} status='failed' ORDER BY priority LIMIT 10""", params
            )]
        counts = {row["status"]: row["count"] for row in rows}
        total = sum(counts.values())
        completed = counts.get("completed", 0)
        return {"total": total, "pending": counts.get("pending", 0),
                "running": counts.get("running", 0), "completed": completed,
                "failed": counts.get("failed", 0),
                "completion_percent": round(completed / total * 100, 1) if total else 0,
                "failures": failures}

    def prepare_price_sync_queue(self, rows: list[dict]) -> int:
        self.prepare_fundamental_sync_queue(rows, 5)
        with self.connect() as connection:
            connection.execute(
                """UPDATE fundamental_sync_queue AS q SET price_status='completed',
                          price_rows=(SELECT COUNT(*) FROM daily_prices p
                                      WHERE p.symbol=q.symbol AND p.market=q.market),
                          price_error=NULL, updated_at=CURRENT_TIMESTAMP
                   WHERE price_status!='completed'
                     AND (SELECT COUNT(*) FROM daily_prices p
                          WHERE p.symbol=q.symbol AND p.market=q.market) >= 500"""
            )
        return len(rows)

    def reset_failed_price_syncs(self) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE fundamental_sync_queue SET price_status='pending', price_error=NULL,
                          updated_at=CURRENT_TIMESTAMP WHERE price_status='failed'"""
            )
        return cursor.rowcount

    def claim_price_sync_batch(self, limit: int) -> list[dict]:
        with self.connect() as connection:
            connection.execute(
                """UPDATE fundamental_sync_queue SET price_status='pending'
                   WHERE price_status='running'
                     AND datetime(updated_at) < datetime('now', '-30 minutes')"""
            )
            rows = [dict(row) for row in connection.execute(
                """SELECT * FROM fundamental_sync_queue WHERE price_status='pending'
                   ORDER BY priority LIMIT ?""", (limit,)
            )]
            connection.executemany(
                """UPDATE fundamental_sync_queue SET price_status='running',
                          updated_at=CURRENT_TIMESTAMP WHERE symbol=? AND market=?""",
                [(row["symbol"], row["market"]) for row in rows],
            )
        return rows

    def finish_price_sync(self, symbol: str, market: str, rows: int = 0,
                          error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE fundamental_sync_queue SET price_status=?, price_rows=?,
                          price_error=?, updated_at=CURRENT_TIMESTAMP
                   WHERE symbol=? AND market=?""",
                ("failed" if error else "completed", rows, error, symbol, market),
            )

    def get_price_sync_progress(self, target_limit: int = 100) -> dict:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT price_status AS status, COUNT(*) AS count
                   FROM fundamental_sync_queue WHERE priority <= ? GROUP BY price_status""",
                (target_limit,),
            ).fetchall()
            failures = [dict(row) for row in connection.execute(
                """SELECT symbol, market, price_error AS error FROM fundamental_sync_queue
                   WHERE priority <= ? AND price_status='failed'
                   ORDER BY priority LIMIT 10""", (target_limit,)
            )]
        counts = {row["status"]: row["count"] for row in rows}
        total = sum(counts.values())
        completed = counts.get("completed", 0)
        return {"total": total, "pending": counts.get("pending", 0),
                "running": counts.get("running", 0), "completed": completed,
                "failed": counts.get("failed", 0),
                "completion_percent": round(completed / total * 100, 1) if total else 0,
                "failures": failures}

    def create_daily_sync_run(self) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO daily_sync_runs(status) VALUES('running')"
            )
        return int(cursor.lastrowid)

    def finish_daily_sync_run(self, run_id: int, status: str, steps_json: str,
                              error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE daily_sync_runs SET status=?, steps_json=?, error=?,
                          finished_at=CURRENT_TIMESTAMP WHERE id=?""",
                (status, steps_json, error, run_id),
            )

    def get_latest_daily_sync_run(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM daily_sync_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

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
            "operating_cash_flow", "capital_expenditure", "free_cash_flow",
            "cash_and_equivalents", "inventory", "property_plant_equipment",
            "share_capital", "interest_expense", "statement_date", "source",
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
                 book_value_per_share, operating_cash_flow, capital_expenditure,
                 free_cash_flow, cash_and_equivalents, inventory,
                 property_plant_equipment, share_capital, interest_expense,
                 statement_date, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, market, fiscal_year, fiscal_quarter) DO UPDATE SET
                report_type=excluded.report_type, revenue=excluded.revenue,
                gross_profit=excluded.gross_profit, operating_income=excluded.operating_income,
                net_income=excluded.net_income, eps=excluded.eps,
                current_assets=excluded.current_assets, total_assets=excluded.total_assets,
                current_liabilities=excluded.current_liabilities,
                total_liabilities=excluded.total_liabilities, equity=excluded.equity,
                book_value_per_share=excluded.book_value_per_share,
                operating_cash_flow=COALESCE(excluded.operating_cash_flow, operating_cash_flow),
                capital_expenditure=COALESCE(excluded.capital_expenditure, capital_expenditure),
                free_cash_flow=COALESCE(excluded.free_cash_flow, free_cash_flow),
                cash_and_equivalents=COALESCE(excluded.cash_and_equivalents, cash_and_equivalents),
                inventory=COALESCE(excluded.inventory, inventory),
                property_plant_equipment=COALESCE(excluded.property_plant_equipment, property_plant_equipment),
                share_capital=COALESCE(excluded.share_capital, share_capital),
                interest_expense=COALESCE(excluded.interest_expense, interest_expense),
                statement_date=COALESCE(excluded.statement_date, statement_date),
                source=COALESCE(excluded.source, source),
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

    def get_fundamentals_coverage(self, symbol: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS financial_periods,
                          COUNT(DISTINCT fiscal_year) AS financial_years,
                          SUM(CASE WHEN operating_cash_flow IS NOT NULL THEN 1 ELSE 0 END)
                            AS cash_flow_periods,
                          SUM(CASE WHEN free_cash_flow IS NOT NULL THEN 1 ELSE 0 END)
                            AS free_cash_flow_periods,
                          MIN(statement_date) AS first_statement_date,
                          MAX(statement_date) AS latest_statement_date
                   FROM financial_snapshots WHERE symbol=?""", (symbol,)
            ).fetchone()
            dividend = connection.execute(
                """SELECT COUNT(*) AS dividend_events,
                          COUNT(DISTINCT substr(ex_date,1,4)) AS dividend_years,
                          MIN(ex_date) AS first_dividend_date,
                          MAX(ex_date) AS latest_dividend_date
                   FROM dividend_events WHERE symbol=? AND cash_dividend > 0""", (symbol,)
            ).fetchone()
        result = {"symbol": symbol, **dict(row), **dict(dividend)}
        periods = result["financial_periods"] or 0
        result["quality_ready"] = bool(
            (result["financial_years"] or 0) >= 5
            and (result["cash_flow_periods"] or 0) >= min(periods, 12)
            and (result["dividend_years"] or 0) >= 3
        )
        return result

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
               (SELECT p3.close FROM daily_prices p3
                WHERE p3.symbol=i.symbol AND p3.market=i.market
                ORDER BY p3.trade_date DESC LIMIT 1 OFFSET 4) AS close_5d_ago,
               (SELECT AVG(p4.close) FROM (
                  SELECT close FROM daily_prices
                  WHERE symbol=i.symbol AND market=i.market
                  ORDER BY trade_date DESC LIMIT 20
                ) p4) AS ma20,
               (SELECT MAX(p5.close) FROM daily_prices p5
                WHERE p5.symbol=i.symbol AND p5.market=i.market
                  AND p5.trade_date >= date(p.trade_date, '-365 day')) AS high_52w,
               r.yoy_percent, r.cumulative_yoy_percent AS annual_revenue_yoy,
               v.pe_ratio, v.pb_ratio, v.dividend_yield,
               (SELECT it.foreign_net FROM institutional_trades it
                WHERE it.symbol=i.symbol AND it.market=i.market
                ORDER BY it.trade_date DESC LIMIT 1) AS foreign_net,
               (SELECT it.trust_net FROM institutional_trades it
                WHERE it.symbol=i.symbol AND it.market=i.market
                ORDER BY it.trade_date DESC LIMIT 1) AS trust_net,
               (SELECT SUM(x.foreign_net) FROM (
                  SELECT foreign_net FROM institutional_trades
                  WHERE symbol=i.symbol AND market=i.market
                  ORDER BY trade_date DESC LIMIT 5
                ) x) AS foreign_net_5d,
               (SELECT SUM(x.trust_net) FROM (
                  SELECT trust_net FROM institutional_trades
                  WHERE symbol=i.symbol AND market=i.market
                  ORDER BY trade_date DESC LIMIT 5
                ) x) AS trust_net_5d,
               (SELECT SUM(x.volume) FROM (
                  SELECT volume FROM daily_prices
                  WHERE symbol=i.symbol AND market=i.market
                  ORDER BY trade_date DESC LIMIT 5
                ) x) AS volume_5d,
               CASE WHEN (SELECT AVG(x.turnover) FROM (
                    SELECT turnover FROM daily_prices
                    WHERE symbol=i.symbol AND market=i.market
                    ORDER BY trade_date DESC LIMIT 20
                  ) x) > 0 THEN p.turnover / (SELECT AVG(x.turnover) FROM (
                    SELECT turnover FROM daily_prices
                    WHERE symbol=i.symbol AND market=i.market
                    ORDER BY trade_date DESC LIMIT 20
                  ) x) END AS turnover_ratio_20d,
               f.fiscal_year, f.fiscal_quarter, f.report_type, f.revenue,
               f.gross_profit, f.operating_income, f.net_income, f.eps,
               f.current_assets, f.total_assets, f.current_liabilities,
               f.total_liabilities, f.equity, f.book_value_per_share
               ,(SELECT COUNT(*) FROM financial_snapshots fh
                 WHERE fh.symbol=i.symbol AND fh.market=i.market) AS financial_periods_count
               ,(SELECT COUNT(*) FROM financial_snapshots fh
                 WHERE fh.symbol=i.symbol AND fh.market=i.market AND fh.eps > 0) AS positive_eps_periods
               ,(SELECT COUNT(DISTINCT fh.fiscal_year) FROM financial_snapshots fh
                 WHERE fh.symbol=i.symbol AND fh.market=i.market AND fh.net_income > 0) AS profitable_years
               ,(SELECT COUNT(DISTINCT substr(d.ex_date,1,4)) FROM dividend_events d
                 WHERE d.symbol=i.symbol AND d.market=i.market
                   AND d.cash_dividend > 0) AS dividend_years
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
