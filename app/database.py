from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from decimal import Decimal

from app.domain import DailyPrice, Instrument


# Direct TWSE/TPEx statements fetched before this rollout were stored in the
# APIs' native NTD-thousands unit.  From this date onward the ingestion layer
# writes TWD and tags the source with ``amount-normalized-x1000`` when relevant.
OFFICIAL_TWD_NORMALIZATION_ROLLOUT_DATE = "2026-08-04"


def _coverage_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%Y-%m"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


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
    published_date TEXT,
    source_as_of_date TEXT,
    source TEXT,
    monetary_unit TEXT,
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
CREATE TABLE IF NOT EXISTS short_term_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'ranking',
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    initial_shares INTEGER NOT NULL,
    remaining_shares INTEGER NOT NULL,
    original_stop REAL NOT NULL,
    active_stop REAL NOT NULL,
    target_price REAL NOT NULL,
    target_reduction_executed INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    closed_at TEXT,
    close_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_short_term_positions_one_open
ON short_term_positions(symbol, market) WHERE status='open';
CREATE INDEX IF NOT EXISTS idx_short_term_positions_status_date
ON short_term_positions(status, entry_date DESC);
CREATE TABLE IF NOT EXISTS short_term_position_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT NOT NULL,
    execution_price REAL NOT NULL,
    shares INTEGER NOT NULL,
    reason TEXT NOT NULL,
    remaining_shares_after INTEGER NOT NULL,
    active_stop_after REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (position_id) REFERENCES short_term_positions(id)
);
CREATE INDEX IF NOT EXISTS idx_short_term_position_events_position_date
ON short_term_position_events(position_id, event_date DESC, id DESC);
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
    price_attempts INTEGER NOT NULL DEFAULT 0,
    price_max_attempts INTEGER NOT NULL DEFAULT 3,
    price_next_retry_at TEXT,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (symbol, market)
);
CREATE INDEX IF NOT EXISTS idx_fundamental_sync_queue_status
ON fundamental_sync_queue(status, priority);
CREATE TABLE IF NOT EXISTS data_sync_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset TEXT NOT NULL,
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    range_start TEXT,
    range_end TEXT,
    priority INTEGER NOT NULL DEFAULT 1000,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    last_source TEXT,
    last_success_at TEXT,
    next_retry_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dataset, market, symbol, range_start, range_end)
);
CREATE INDEX IF NOT EXISTS idx_data_sync_jobs_dispatch
ON data_sync_jobs(dataset, status, priority, updated_at);
CREATE TABLE IF NOT EXISTS data_sync_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT,
    status TEXT NOT NULL,
    rows_written INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    FOREIGN KEY(job_id) REFERENCES data_sync_jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_data_sync_attempts_job
ON data_sync_attempts(job_id, attempted_at DESC);
CREATE TABLE IF NOT EXISTS data_source_health (
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    last_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_rows_written INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, dataset)
);
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
    overheat_score REAL,
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
CREATE TABLE IF NOT EXISTS short_term_ranking_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,
    requested_date TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT,
    industry TEXT,
    rank INTEGER NOT NULL,
    attention_grade TEXT NOT NULL,
    attention_score REAL NOT NULL,
    operation_status TEXT NOT NULL,
    signal_close REAL NOT NULL,
    market_close REAL,
    market_mode TEXT,
    peer_symbols_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, strategy_version, symbol, market)
);
CREATE INDEX IF NOT EXISTS idx_short_term_ranking_date_rank
ON short_term_ranking_snapshots(strategy_version, signal_date DESC, rank);
CREATE TABLE IF NOT EXISTS short_term_ranking_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_date TEXT NOT NULL,
    requested_date TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    market_date TEXT,
    coverage_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    turnover_percent REAL,
    changes_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(signal_date, strategy_version)
);
CREATE INDEX IF NOT EXISTS idx_short_term_ranking_runs_date
ON short_term_ranking_runs(strategy_version, signal_date DESC);
CREATE TABLE IF NOT EXISTS short_term_ranking_run_items (
    run_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT,
    industry TEXT,
    rank INTEGER NOT NULL,
    attention_grade TEXT NOT NULL,
    attention_score REAL NOT NULL,
    operation_status TEXT NOT NULL,
    signal_close REAL NOT NULL,
    market_close REAL,
    market_mode TEXT,
    peer_symbols_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    item_json TEXT NOT NULL,
    PRIMARY KEY (run_id, symbol, market),
    UNIQUE (run_id, rank),
    FOREIGN KEY (run_id) REFERENCES short_term_ranking_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_short_term_ranking_run_items_run_rank
ON short_term_ranking_run_items(run_id, rank);
CREATE TABLE IF NOT EXISTS vnext_recommendation_runs (
    snapshot_date TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vnext_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_vnext_backtest_runs_created
ON vnext_backtest_runs(created_at DESC);
CREATE TABLE IF NOT EXISTS daily_decision_logs (
    decision_date TEXT PRIMARY KEY,
    market_context_json TEXT NOT NULL,
    quality_snapshot_id INTEGER,
    vnext_snapshot_date TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(quality_snapshot_id) REFERENCES data_quality_snapshots(id)
);
CREATE TABLE IF NOT EXISTS data_quality_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_data_quality_snapshots_generated
ON data_quality_snapshots(generated_at DESC);
CREATE TABLE IF NOT EXISTS analysis_sync_state (
    symbol TEXT NOT NULL,
    dataset TEXT NOT NULL,
    last_attempt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (symbol, dataset)
);
CREATE TABLE IF NOT EXISTS strategy_experiment_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_key TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    train_start TEXT,
    train_end TEXT,
    out_of_sample_start TEXT,
    out_of_sample_end TEXT,
    lookahead_audit_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_strategy_experiment_runs_key_created
ON strategy_experiment_runs(strategy_key, created_at DESC);
CREATE TABLE IF NOT EXISTS paper_strategy_candidates (
    strategy_key TEXT PRIMARY KEY,
    strategy_version TEXT NOT NULL,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    promotion_policy_json TEXT NOT NULL,
    locked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS paper_portfolio_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_key TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    side TEXT NOT NULL,
    target_weight_percent REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    execution_date TEXT,
    execution_price REAL,
    shares REAL,
    costs REAL NOT NULL DEFAULT 0,
    data_version_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(strategy_key) REFERENCES paper_strategy_candidates(strategy_key)
);
CREATE INDEX IF NOT EXISTS idx_paper_orders_strategy_status
ON paper_portfolio_orders(strategy_key, status, signal_date);
CREATE TABLE IF NOT EXISTS paper_portfolio_positions (
    strategy_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    shares REAL NOT NULL,
    average_cost REAL NOT NULL,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(strategy_key, symbol, market),
    FOREIGN KEY(strategy_key) REFERENCES paper_strategy_candidates(strategy_key)
);
CREATE TABLE IF NOT EXISTS paper_portfolio_valuations (
    strategy_key TEXT NOT NULL,
    valuation_date TEXT NOT NULL,
    cash REAL NOT NULL,
    holdings_value REAL NOT NULL,
    nav REAL NOT NULL,
    benchmark_nav REAL,
    benchmark_close REAL,
    transaction_costs REAL NOT NULL DEFAULT 0,
    data_version_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(strategy_key, valuation_date),
    FOREIGN KEY(strategy_key) REFERENCES paper_strategy_candidates(strategy_key)
);
CREATE INDEX IF NOT EXISTS idx_paper_valuations_strategy_date
ON paper_portfolio_valuations(strategy_key, valuation_date DESC);
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
                "statement_date": "TEXT", "published_date": "TEXT",
                "source_as_of_date": "TEXT", "source": "TEXT",
                "monetary_unit": "TEXT",
            }
            for name, sql_type in additions.items():
                if name not in financial_columns:
                    connection.execute(
                        f"ALTER TABLE financial_snapshots ADD COLUMN {name} {sql_type}"
                    )
            connection.execute(
                """UPDATE financial_snapshots
                   SET source_as_of_date=COALESCE(source_as_of_date, published_date),
                       published_date=NULL
                   WHERE published_date IS NOT NULL
                     AND (source LIKE 'TWSE official OpenAPI%'
                          OR source LIKE 'TPEx official OpenAPI%')"""
            )
            self._normalize_official_financial_units(connection)
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
                "price_attempts": "INTEGER NOT NULL DEFAULT 0",
                "price_max_attempts": "INTEGER NOT NULL DEFAULT 3",
                "price_next_retry_at": "TEXT",
                "created_at": "TEXT",
            }.items():
                if name not in queue_columns:
                    connection.execute(
                        f"ALTER TABLE fundamental_sync_queue ADD COLUMN {name} {definition}"
                    )
            job_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(data_sync_jobs)")
            }
            if "next_retry_at" not in job_columns:
                connection.execute("ALTER TABLE data_sync_jobs ADD COLUMN next_retry_at TEXT")
            index_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(market_index_snapshots)")
            }
            if "overheat_score" not in index_columns:
                connection.execute("ALTER TABLE market_index_snapshots ADD COLUMN overheat_score REAL")
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
            paper_valuation_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(paper_portfolio_valuations)")
            }
            for name, definition in {"benchmark_nav": "REAL", "benchmark_close": "REAL"}.items():
                if name not in paper_valuation_columns:
                    connection.execute(f"ALTER TABLE paper_portfolio_valuations ADD COLUMN {name} {definition}")
            position_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(short_term_positions)")
            }
            if "source" not in position_columns:
                connection.execute(
                    "ALTER TABLE short_term_positions ADD COLUMN source TEXT NOT NULL DEFAULT 'ranking'"
                )
            connection.execute("PRAGMA optimize")

    @staticmethod
    def _normalize_official_financial_units(connection: sqlite3.Connection) -> int:
        """Convert legacy official statements from NTD thousands to NTD.

        Prefer the quarter-revenue ratio where available.  For rows without
        matching revenue data, use the recorded ingestion rollout boundary and
        source provenance.  ``monetary_unit IS NULL`` is the idempotency guard.
        """
        rows = connection.execute(
            """SELECT f.rowid, f.revenue, f.source, f.fetched_at,
                      r.cumulative_revenue
               FROM financial_snapshots f
               LEFT JOIN monthly_revenues r
                 ON r.symbol=f.symbol AND r.market=f.market
                AND r.revenue_month=printf('%04d-%02d', f.fiscal_year,
                                           f.fiscal_quarter * 3)
               WHERE f.monetary_unit IS NULL
                 AND (f.source LIKE 'TWSE official OpenAPI%'
                      OR f.source LIKE 'TPEx official OpenAPI%')"""
        ).fetchall()
        normalized = 0
        monetary_fields = (
            "revenue", "gross_profit", "operating_income", "net_income",
            "current_assets", "total_assets", "current_liabilities",
            "total_liabilities", "equity",
        )
        assignments = ", ".join(
            f"{field}=CASE WHEN {field} IS NULL THEN NULL ELSE {field} * 1000 END"
            for field in monetary_fields
        )
        for row in rows:
            source = str(row["source"] or "")
            fetched_at = str(row["fetched_at"] or "")
            explicitly_normalized = "amount-normalized-x1000" in source
            before_rollout = (
                bool(fetched_at)
                and fetched_at[:10] < OFFICIAL_TWD_NORMALIZATION_ROLLOUT_DATE
            )
            ratio = None
            if (
                row["revenue"] is not None
                and row["cumulative_revenue"] not in (None, 0)
            ):
                ratio = (
                    abs(float(row["revenue"]))
                    / abs(float(row["cumulative_revenue"]))
                )

            should_scale = (
                not explicitly_normalized
                and ((ratio is not None and 0.8 <= ratio <= 1.2)
                     or (ratio is None and before_rollout))
            )
            already_twd = (
                explicitly_normalized
                or (ratio is not None and 800 <= ratio <= 1200)
                or (not before_rollout and bool(fetched_at))
            )
            if should_scale:
                connection.execute(
                    f"""UPDATE financial_snapshots
                        SET {assignments}, monetary_unit='TWD'
                        WHERE rowid=?""",
                    (row["rowid"],),
                )
                normalized += 1
            elif already_twd:
                connection.execute(
                    "UPDATE financial_snapshots SET monetary_unit='TWD' WHERE rowid=?",
                    (row["rowid"],),
                )
        return normalized

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
        WITH ranked_prices AS (
            SELECT p.symbol, p.market, p.trade_date, p.close,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.symbol, p.market ORDER BY p.trade_date DESC
                   ) AS price_rank,
                   MAX(p.close) OVER (PARTITION BY p.symbol, p.market) AS all_time_high_close
            FROM daily_prices p
            JOIN watchlist selected
              ON selected.symbol=p.symbol AND selected.market=p.market
        ), market_latest AS (
            SELECT market, MAX(trade_date) AS trade_date
            FROM daily_prices WHERE close > 0 GROUP BY market
        )
        SELECT w.symbol, w.market, w.added_at, w.average_cost, w.shares,
               w.purchase_date, w.stop_loss, w.target_price, w.investment_horizon,
               w.notes, i.name, i.industry,
               latest.trade_date, latest.close,
               previous.close AS previous_close,
               market_latest.trade_date AS market_latest_date,
               latest.all_time_high_close
        FROM watchlist w
        JOIN instruments i ON i.symbol=w.symbol AND i.market=w.market
        LEFT JOIN ranked_prices latest ON latest.symbol=w.symbol AND latest.market=w.market
          AND latest.price_rank=1
        LEFT JOIN ranked_prices previous ON previous.symbol=w.symbol AND previous.market=w.market
          AND previous.price_rank=2
        LEFT JOIN market_latest ON market_latest.market=w.market
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

    def list_research_sync_universe(self, limit: int | None = None) -> list[dict]:
        """Return current instruments with liquid names first and no price-only omissions."""
        popular = self.list_popular_stocks(limit or 100_000)
        seen = {(row["symbol"], row["market"]) for row in popular}
        with self.connect() as connection:
            remaining = [dict(row) for row in connection.execute(
                """SELECT symbol,name,market,industry FROM instruments
                   ORDER BY market,symbol"""
            ) if (row["symbol"], row["market"]) not in seen]
        rows = popular + remaining
        return rows[:limit] if limit else rows

    def reset_failed_fundamental_syncs(self, quota_cooldown_minutes: int = 60,
                                      max_attempts: int = 3) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE fundamental_sync_queue SET status='pending', error=NULL,
                          updated_at=CURRENT_TIMESTAMP WHERE status='failed'
                     AND (LOWER(COALESCE(error,'')) NOT LIKE '%quota%'
                          OR datetime(updated_at) <= datetime('now', ?))
                     AND attempts < ?""",
                (f"-{max(1, quota_cooldown_minutes)} minutes", max(1, max_attempts)),
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
            quota_where = condition + (" AND" if condition else "WHERE")
            quota_limited = connection.execute(
                f"""SELECT COUNT(*) FROM fundamental_sync_queue {quota_where}
                    status='failed' AND LOWER(COALESCE(error,'')) LIKE '%quota%'""", params
            ).fetchone()[0]
            terminal_failed = connection.execute(
                f"""SELECT COUNT(*) FROM fundamental_sync_queue {failure_where}
                    status='failed' AND attempts >= 3""", params
            ).fetchone()[0]
            oldest_pending_at = connection.execute(
                f"""SELECT MIN(created_at) FROM fundamental_sync_queue {condition}
                    {'AND' if condition else 'WHERE'} status IN ('pending','failed','running')""",
                params,
            ).fetchone()[0]
        counts = {row["status"]: row["count"] for row in rows}
        total = sum(counts.values())
        completed = counts.get("completed", 0)
        return {"total": total, "pending": counts.get("pending", 0),
                "running": counts.get("running", 0), "completed": completed,
                "failed": counts.get("failed", 0),
                "remaining": total - completed,
                "quota_limited": quota_limited,
                "terminal_failed": terminal_failed,
                "oldest_pending_at": oldest_pending_at,
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
                   WHERE price_status NOT IN ('completed', 'short_history', 'terminal_failed')
                     AND (SELECT COUNT(*) FROM daily_prices p
                          WHERE p.symbol=q.symbol AND p.market=q.market) >= 500"""
            )
        return len(rows)

    def reset_failed_price_syncs(self, quota_cooldown_minutes: int = 60) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE fundamental_sync_queue SET price_status='pending', price_error=NULL,
                          updated_at=CURRENT_TIMESTAMP WHERE price_status='failed'
                     AND price_attempts < price_max_attempts
                     AND (price_next_retry_at IS NULL OR price_next_retry_at<=CURRENT_TIMESTAMP)
                     AND (LOWER(COALESCE(price_error,'')) NOT LIKE '%quota%'
                          OR datetime(updated_at) <= datetime('now', ?))""",
                (f"-{max(1, quota_cooldown_minutes)} minutes",),
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
                   AND (price_next_retry_at IS NULL OR price_next_retry_at<=CURRENT_TIMESTAMP)
                   ORDER BY priority LIMIT ?""", (limit,)
            )]
            connection.executemany(
                """UPDATE fundamental_sync_queue SET price_status='running', price_attempts=price_attempts+1,
                          updated_at=CURRENT_TIMESTAMP WHERE symbol=? AND market=?""",
                [(row["symbol"], row["market"]) for row in rows],
            )
        return rows

    def finish_price_sync(self, symbol: str, market: str, rows: int = 0,
                          error: str | None = None,
                          status: str | None = None) -> None:
        with self.connect() as connection:
            job = connection.execute(
                """SELECT price_attempts,price_max_attempts FROM fundamental_sync_queue
                   WHERE symbol=? AND market=?""", (symbol, market)
            ).fetchone()
            failed_status = "terminal_failed" if job and job["price_attempts"] >= job["price_max_attempts"] else "failed"
            next_retry = "datetime('now', '+60 minutes')" if error and "quota" in error.lower() else "datetime('now', '+5 minutes')"
            connection.execute(
                """UPDATE fundamental_sync_queue SET price_status=?, price_rows=?,
                          price_error=?, price_next_retry_at=CASE WHEN ? IS NULL THEN NULL
                          WHEN ?='terminal_failed' THEN NULL ELSE """ + next_retry + """ END,
                          updated_at=CURRENT_TIMESTAMP
                   WHERE symbol=? AND market=?""",
                (status or (failed_status if error else "completed"), rows, error, error,
                 status or (failed_status if error else "completed"), symbol, market),
            )

    def get_price_sync_progress(self, target_limit: int | None = 100) -> dict:
        condition = "WHERE priority <= ?" if target_limit else ""
        params = (target_limit,) if target_limit else ()
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT price_status AS status, COUNT(*) AS count
                   FROM fundamental_sync_queue %s GROUP BY price_status""" % condition,
                params,
            ).fetchall()
            failures = [dict(row) for row in connection.execute(
                """SELECT symbol, market, price_error AS error FROM fundamental_sync_queue
                   %s %s price_status='failed'
                   ORDER BY priority LIMIT 10""" % (condition, "AND" if condition else "WHERE"),
                params,
            )]
        counts = {row["status"]: row["count"] for row in rows}
        total = sum(counts.values())
        completed = counts.get("completed", 0)
        short_history = counts.get("short_history", 0)
        resolved = completed + short_history
        return {"total": total, "pending": counts.get("pending", 0),
                "running": counts.get("running", 0), "completed": completed,
                "short_history": short_history,
                "failed": counts.get("failed", 0),
                "terminal_failed": counts.get("terminal_failed", 0),
                "completion_percent": round(resolved / total * 100, 1) if total else 0,
                "failures": failures}

    def enqueue_data_sync_jobs(self, dataset: str, rows: list[dict],
                               range_start: str | None = None,
                               range_end: str | None = None) -> int:
        """Persist a dataset × stock × date-range audit trail without resetting progress."""
        with self.connect() as connection:
            connection.executemany(
                """INSERT INTO data_sync_jobs(dataset,market,symbol,range_start,range_end,priority)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(dataset,market,symbol,range_start,range_end)
                   DO UPDATE SET priority=excluded.priority, updated_at=CURRENT_TIMESTAMP""",
                [(dataset, row["market"], row["symbol"], range_start, range_end, index)
                 for index, row in enumerate(rows, 1)],
            )
        return len(rows)

    def record_data_sync_attempt(self, dataset: str, symbol: str, market: str,
                                 rows_written: int = 0, error: str | None = None,
                                 source: str | None = None) -> None:
        with self.connect() as connection:
            job = connection.execute(
                """SELECT id,attempts,max_attempts FROM data_sync_jobs
                   WHERE dataset=? AND symbol=? AND market=?
                   ORDER BY id DESC LIMIT 1""", (dataset, symbol, market),
            ).fetchone()
            if not job:
                return
            status = "completed" if error is None else (
                "terminal_failed" if job["attempts"] + 1 >= job["max_attempts"] else "failed"
            )
            retry_at = (
                None if error is None or status == "terminal_failed"
                else ("+60 minutes" if "quota" in error.lower() else "+5 minutes")
            )
            connection.execute(
                """UPDATE data_sync_jobs SET status=?, attempts=attempts+1,
                   last_error=?, last_source=?, last_success_at=
                   CASE WHEN ? IS NULL THEN CURRENT_TIMESTAMP ELSE last_success_at END,
                   next_retry_at=CASE WHEN ? IS NULL THEN NULL
                                      WHEN ?='terminal_failed' THEN NULL
                                      ELSE datetime('now', ?) END,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (status, error, source, error, error, status, retry_at, job["id"]),
            )
            connection.execute(
                """INSERT INTO data_sync_attempts(job_id,source,status,rows_written,error)
                   VALUES(?,?,?,?,?)""",
                (job["id"], source, status, rows_written, error),
            )

    def reset_retryable_data_sync_jobs(self, dataset: str | None = None) -> int:
        """Release only failed audit jobs whose cooldown has elapsed.

        The queue remains durable across daily runs: terminal failures require a
        deliberate data/source repair rather than silently restarting forever.
        """
        condition = "AND dataset=?" if dataset else ""
        params = (dataset,) if dataset else ()
        with self.connect() as connection:
            cursor = connection.execute(
                f"""UPDATE data_sync_jobs SET status='pending', updated_at=CURRENT_TIMESTAMP
                    WHERE status='failed' AND attempts < max_attempts
                      AND (next_retry_at IS NULL OR next_retry_at<=CURRENT_TIMESTAMP) {condition}""",
                params,
            )
        return cursor.rowcount

    def get_data_sync_job_progress(self, dataset: str | None = None) -> dict:
        condition = "WHERE dataset=?" if dataset else ""
        params = (dataset,) if dataset else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT status,COUNT(*) AS count FROM data_sync_jobs {condition} GROUP BY status",
                params,
            ).fetchall()
            failures = [dict(row) for row in connection.execute(
                f"""SELECT dataset,market,symbol,last_error,attempts,max_attempts,last_source
                    FROM data_sync_jobs {condition} AND status IN ('failed','terminal_failed')
                    ORDER BY priority LIMIT 10""" if condition else
                """SELECT dataset,market,symbol,last_error,attempts,max_attempts,last_source
                   FROM data_sync_jobs WHERE status IN ('failed','terminal_failed')
                   ORDER BY priority LIMIT 10""", params,
            )]
        counts = {row["status"]: row["count"] for row in rows}
        total = sum(counts.values())
        return {"total": total, "pending": counts.get("pending", 0),
                "completed": counts.get("completed", 0), "failed": counts.get("failed", 0),
                "terminal_failed": counts.get("terminal_failed", 0), "failures": failures}

    def record_data_source_health(self, source: str, dataset: str, *,
                                  rows_written: int = 0,
                                  error: str | None = None) -> None:
        """Keep a compact, durable signal for provider availability and fallback use."""
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO data_source_health
                   (source,dataset,last_success_at,consecutive_failures,last_error,last_rows_written)
                   VALUES(?,?,CASE WHEN ? IS NULL THEN CURRENT_TIMESTAMP END,
                          CASE WHEN ? IS NULL THEN 0 ELSE 1 END,?,?)
                   ON CONFLICT(source,dataset) DO UPDATE SET
                     last_attempt_at=CURRENT_TIMESTAMP,
                     last_success_at=CASE WHEN excluded.last_error IS NULL
                                          THEN CURRENT_TIMESTAMP
                                          ELSE data_source_health.last_success_at END,
                     consecutive_failures=CASE WHEN excluded.last_error IS NULL THEN 0
                                               ELSE data_source_health.consecutive_failures+1 END,
                     last_error=excluded.last_error,
                     last_rows_written=excluded.last_rows_written""",
                (source, dataset, error, error, error, rows_written),
            )

    def get_data_source_health(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT source,dataset,last_attempt_at,last_success_at,consecutive_failures,
                          last_error,last_rows_written
                   FROM data_source_health ORDER BY consecutive_failures DESC, source, dataset"""
            ).fetchall()
        return [dict(row) for row in rows]

    def create_daily_sync_run(self, stale_after_minutes: int = 360) -> int | None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE daily_sync_runs
                   SET status='failed', error='stale running job recovered on next start',
                       finished_at=CURRENT_TIMESTAMP
                   WHERE status='running' AND started_at < datetime('now', ?)""",
                (f"-{max(1, stale_after_minutes)} minutes",),
            )
            running = connection.execute(
                "SELECT id FROM daily_sync_runs WHERE status='running' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if running:
                return None
            cursor = connection.execute(
                "INSERT INTO daily_sync_runs(status) VALUES('running')"
            )
        return int(cursor.lastrowid)

    def update_daily_sync_progress(self, run_id: int, steps_json: str) -> None:
        """Persist completed steps while a long sync is still running."""
        with self.connect() as connection:
            connection.execute(
                "UPDATE daily_sync_runs SET steps_json=? WHERE id=? AND status='running'",
                (steps_json, run_id),
            )

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

    def get_market_data_freshness(self) -> dict:
        """Expose per-market coverage so a completed job cannot hide stale stocks."""
        datasets = (
            ("prices", "daily_prices", "trade_date", 7),
            ("revenues", "monthly_revenues", "revenue_month", 45),
            ("valuations", "valuations", "valuation_date", 14),
            ("financials", "financial_snapshots", "statement_date", 190),
            ("institutions", "institutional_trades", "trade_date", 7),
        )
        result: dict[str, dict] = {}
        with self.connect() as connection:
            markets = [row[0] for row in connection.execute(
                "SELECT DISTINCT market FROM instruments ORDER BY market"
            )]
            for market in markets:
                total = connection.execute(
                    "SELECT COUNT(*) FROM instruments WHERE market=?", (market,)
                ).fetchone()[0]
                coverage = {}
                for name, table, column, tolerance_days in datasets:
                    rows = connection.execute(
                        f"""SELECT d.symbol,MAX(d.{column}) latest_date
                            FROM {table} d JOIN instruments i
                              ON i.symbol=d.symbol AND i.market=d.market
                            WHERE d.market=? GROUP BY d.symbol""", (market,)
                    ).fetchall()
                    parsed = [(row[0], _coverage_date(row[1])) for row in rows]
                    valid_dates = [item[1] for item in parsed if item[1] is not None]
                    latest_date = max(valid_dates) if valid_dates else None
                    cutoff = latest_date - timedelta(days=tolerance_days) if latest_date else None
                    current = sum(item_date is not None and cutoff is not None and item_date >= cutoff
                                  for _, item_date in parsed)
                    exact = sum(item_date == latest_date for _, item_date in parsed)
                    coverage[name] = {
                        "latest_date": latest_date.isoformat() if latest_date else None,
                        "covered_stocks": current,
                        "total_stocks": total,
                        "coverage_percent": round(current / total * 100, 1) if total else 0,
                        "stale_stocks": max(0, total - current),
                        "exact_date_stocks": exact,
                        "exact_date_coverage_percent": (
                            round(exact / total * 100, 1) if total else 0
                        ),
                        "off_latest_date_stocks": max(0, total - exact),
                    }
                    if name == "institutions":
                        coverage[name]["exact_date_coverage_of_covered_percent"] = (
                            round(exact / current * 100, 1) if current else 0
                        )
                result[market] = coverage
        return result

    def list_market_dataset_lagging_symbols(
        self,
        market: str,
        dataset: str,
        *,
        limit: int = 20,
    ) -> dict:
        """List instruments that are not aligned to a dataset's latest market date."""
        specs = {
            "prices": ("daily_prices", "trade_date"),
            "institutions": ("institutional_trades", "trade_date"),
        }
        if dataset not in specs:
            raise ValueError(f"Unsupported exact-date dataset: {dataset}")
        table, column = specs[dataset]
        with self.connect() as connection:
            latest_row = connection.execute(
                f"SELECT MAX({column}) FROM {table} WHERE market=?", (market,)
            ).fetchone()
            latest_date = latest_row[0] if latest_row else None
            rows = [dict(row) for row in connection.execute(
                f"""SELECT i.symbol,i.name,MAX(d.{column}) AS latest_date
                    FROM instruments i
                    LEFT JOIN {table} d
                      ON d.symbol=i.symbol AND d.market=i.market
                    WHERE i.market=?
                    GROUP BY i.symbol,i.name
                    HAVING latest_date IS NULL OR latest_date<>?
                    ORDER BY latest_date IS NOT NULL,latest_date,i.symbol""",
                (market, latest_date),
            )]
        return {
            "market": market,
            "dataset": dataset,
            "target_date": latest_date,
            "lagging_count": len(rows),
            "samples": rows[:max(0, limit)],
        }

    def get_market_cached_counts(self, market: str) -> dict[str, int]:
        """Return cache size used when an official market endpoint is unavailable."""
        with self.connect() as connection:
            instruments = connection.execute(
                "SELECT COUNT(*) FROM instruments WHERE market=?", (market,)
            ).fetchone()[0]
            prices = connection.execute(
                "SELECT COUNT(*) FROM daily_prices WHERE market=?", (market,)
            ).fetchone()[0]
        return {"instruments": instruments, "prices": prices}

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

    def get_institutional_trades(
        self,
        symbol: str,
        limit: int = 120,
        *,
        end_date: str | None = None,
        market: str | None = None,
    ) -> list[dict]:
        conditions = ["symbol=?"]
        params: list[object] = [symbol]
        if market:
            conditions.append("market=?")
            params.append(market)
        if end_date:
            conditions.append("trade_date<=?")
            params.append(end_date)
        params.append(limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM institutional_trades
                WHERE {' AND '.join(conditions)}
                ORDER BY trade_date DESC LIMIT ?""", params
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

    def save_vnext_recommendation_run(self, snapshot_date: str, payload_json: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO vnext_recommendation_runs(snapshot_date,payload_json)
                   VALUES(?,?) ON CONFLICT(snapshot_date) DO UPDATE SET
                   payload_json=excluded.payload_json, created_at=CURRENT_TIMESTAMP""",
                (snapshot_date, payload_json),
            )

    def get_latest_vnext_recommendation_run(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM vnext_recommendation_runs ORDER BY snapshot_date DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def save_vnext_backtest_run(self, started_at: str, ended_at: str,
                                parameters_json: str, result_json: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO vnext_backtest_runs
                   (started_at,ended_at,parameters_json,result_json) VALUES(?,?,?,?)""",
                (started_at, ended_at, parameters_json, result_json),
            )
        return int(cursor.lastrowid)

    def get_recent_vnext_backtest_run(self, parameters_json: str,
                                      max_age_minutes: int = 15) -> dict | None:
        """Avoid repeating an expensive read/write backtest for identical inputs."""
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM vnext_backtest_runs
                   WHERE parameters_json=?
                     AND datetime(created_at)>=datetime('now', ?)
                   ORDER BY id DESC LIMIT 1""",
                (parameters_json, f"-{max(1, max_age_minutes)} minutes"),
            ).fetchone()
        return dict(row) if row else None

    def save_strategy_experiment_run(self, strategy_key: str, strategy_version: str,
                                     parameters_json: str, lookahead_audit_json: str,
                                     result_json: str, status: str,
                                     train_start: str | None = None, train_end: str | None = None,
                                     out_of_sample_start: str | None = None,
                                     out_of_sample_end: str | None = None) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO strategy_experiment_runs
                   (strategy_key,strategy_version,parameters_json,train_start,train_end,
                    out_of_sample_start,out_of_sample_end,lookahead_audit_json,result_json,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (strategy_key, strategy_version, parameters_json, train_start, train_end,
                 out_of_sample_start, out_of_sample_end, lookahead_audit_json, result_json, status),
            )
        return int(cursor.lastrowid)

    def list_strategy_experiment_runs(self, strategy_key: str | None = None,
                                      limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            if strategy_key:
                rows = connection.execute(
                    """SELECT * FROM strategy_experiment_runs WHERE strategy_key=?
                       ORDER BY id DESC LIMIT ?""", (strategy_key, limit)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM strategy_experiment_runs ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def upsert_paper_strategy_candidate(self, strategy_key: str, strategy_version: str,
                                        status: str, parameters_json: str,
                                        promotion_policy_json: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO paper_strategy_candidates
                   (strategy_key,strategy_version,status,parameters_json,promotion_policy_json)
                   VALUES(?,?,?,?,?) ON CONFLICT(strategy_key) DO UPDATE SET
                   strategy_version=excluded.strategy_version,status=excluded.status,
                   parameters_json=excluded.parameters_json,
                   promotion_policy_json=excluded.promotion_policy_json,
                   updated_at=CURRENT_TIMESTAMP""",
                (strategy_key, strategy_version, status, parameters_json, promotion_policy_json),
            )

    def list_paper_strategy_candidates(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM paper_strategy_candidates ORDER BY strategy_key").fetchall()
        return [dict(row) for row in rows]

    def list_paper_orders(self, strategy_key: str, status: str | None = None) -> list[dict]:
        with self.connect() as connection:
            sql = "SELECT * FROM paper_portfolio_orders WHERE strategy_key=?"
            params: list[object] = [strategy_key]
            if status:
                sql += " AND status=?"
                params.append(status)
            sql += " ORDER BY id"
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_latest_paper_order(self, strategy_key: str, symbol: str, market: str,
                               side: str, status: str = "executed") -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM paper_portfolio_orders WHERE strategy_key=? AND symbol=? AND market=?
                   AND side=? AND status=? ORDER BY id DESC LIMIT 1""",
                (strategy_key, symbol, market, side, status),
            ).fetchone()
        return dict(row) if row else None

    def add_paper_order(self, row: dict) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO paper_portfolio_orders
                   (strategy_key,signal_date,symbol,market,side,target_weight_percent,data_version_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (row["strategy_key"], row["signal_date"], row["symbol"], row["market"], row["side"],
                 row["target_weight_percent"], row["data_version_json"]),
            )
        return int(cursor.lastrowid)

    def execute_paper_order(self, order_id: int, execution_date: str, execution_price: float,
                            shares: float, costs: float, status: str = "executed") -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE paper_portfolio_orders SET status=?,execution_date=?,execution_price=?,shares=?,costs=?
                   WHERE id=?""", (status, execution_date, execution_price, shares, costs, order_id)
            )

    def upsert_paper_position(self, strategy_key: str, symbol: str, market: str,
                              shares: float, average_cost: float, opened_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO paper_portfolio_positions(strategy_key,symbol,market,shares,average_cost,opened_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(strategy_key,symbol,market) DO UPDATE SET
                   shares=excluded.shares,average_cost=excluded.average_cost,updated_at=CURRENT_TIMESTAMP""",
                (strategy_key, symbol, market, shares, average_cost, opened_at),
            )

    def remove_paper_position(self, strategy_key: str, symbol: str, market: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM paper_portfolio_positions WHERE strategy_key=? AND symbol=? AND market=?",
                               (strategy_key, symbol, market))

    def list_paper_positions(self, strategy_key: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM paper_portfolio_positions WHERE strategy_key=?",
                                      (strategy_key,)).fetchall()
        return [dict(row) for row in rows]

    def get_latest_paper_valuation(self, strategy_key: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM paper_portfolio_valuations WHERE strategy_key=? ORDER BY valuation_date DESC LIMIT 1",
                (strategy_key,)).fetchone()
        return dict(row) if row else None

    def save_paper_valuation(self, row: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO paper_portfolio_valuations
                   (strategy_key,valuation_date,cash,holdings_value,nav,benchmark_nav,benchmark_close,transaction_costs,data_version_json)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(strategy_key,valuation_date) DO UPDATE SET
                   cash=excluded.cash,holdings_value=excluded.holdings_value,nav=excluded.nav,
                   benchmark_nav=excluded.benchmark_nav,benchmark_close=excluded.benchmark_close,
                   transaction_costs=excluded.transaction_costs,data_version_json=excluded.data_version_json,
                   created_at=CURRENT_TIMESTAMP""",
                (row["strategy_key"], row["valuation_date"], row["cash"], row["holdings_value"], row["nav"],
                 row.get("benchmark_nav"), row.get("benchmark_close"), row["transaction_costs"], row["data_version_json"]),
            )

    def list_paper_valuations(self, strategy_key: str, limit: int = 365) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM paper_portfolio_valuations WHERE strategy_key=?
                   ORDER BY valuation_date DESC LIMIT ?""", (strategy_key, limit)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def save_daily_decision_log(self, decision_date: str, market_context_json: str,
                                payload_json: str, quality_snapshot_id: int | None = None,
                                vnext_snapshot_date: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO daily_decision_logs
                   (decision_date,market_context_json,quality_snapshot_id,vnext_snapshot_date,payload_json)
                   VALUES(?,?,?,?,?) ON CONFLICT(decision_date) DO UPDATE SET
                   market_context_json=excluded.market_context_json,
                   quality_snapshot_id=excluded.quality_snapshot_id,
                   vnext_snapshot_date=excluded.vnext_snapshot_date,
                   payload_json=excluded.payload_json,created_at=CURRENT_TIMESTAMP""",
                (decision_date, market_context_json, quality_snapshot_id,
                 vnext_snapshot_date, payload_json),
            )

    def list_daily_decision_logs(self, limit: int = 30) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM daily_decision_logs ORDER BY decision_date DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def save_data_quality_snapshot(self, generated_at: str, status: str, report_json: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO data_quality_snapshots(generated_at,status,report_json)
                   VALUES(?,?,?)""",
                (generated_at, status, report_json),
            )
            return int(cursor.lastrowid)

    def list_data_quality_snapshots(self, limit: int = 30) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT id,generated_at,status,report_json FROM data_quality_snapshots
                   ORDER BY id DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

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
                financial_period=COALESCE(excluded.financial_period, valuations.financial_period),
                fetched_at=CURRENT_TIMESTAMP""",
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
            "share_capital", "interest_expense", "statement_date", "published_date",
            "source_as_of_date", "source", "monetary_unit",
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
                 statement_date, published_date, source_as_of_date, source,
                 monetary_unit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                published_date=COALESCE(excluded.published_date, published_date),
                source_as_of_date=COALESCE(excluded.source_as_of_date, source_as_of_date),
                source=COALESCE(excluded.source, source),
                monetary_unit=COALESCE(excluded.monetary_unit, monetary_unit),
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
