from pathlib import Path
from threading import Event
from time import sleep

from fastapi.testclient import TestClient

from app.database import Database
from app.short_term_ranking_backtest import (
    _effectiveness_assessment,
    short_term_ranking_backtest,
)
from app.short_term_fundamentals import load_short_term_fundamental_assessment


def _coverage(signal_date: str, ready: int = 100) -> dict:
    total = {
        "current_universe_symbols": 100,
        "price_ready_symbols": ready,
        "financial_ready_symbols": ready,
        "valuation_ready_symbols": ready,
        "revenue_ready_symbols": ready,
        "institution_ready_symbols": ready,
        "core_ready_symbols": ready,
        "full_factor_ready_symbols": ready,
    }
    return {"as_of": signal_date, "markets": [], "total": total}


def _seed_paths(database: Database) -> list[str]:
    dates = [
        "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
        "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13",
        "2026-01-14", "2026-01-15", "2026-01-16",
    ]
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO instruments(symbol,market,name,industry) VALUES(?,?,?,?)",
            [(symbol, "TWSE", symbol, "technology")
             for symbol in ("A", "P1", "P2", "P3")],
        )
        connection.executemany(
            """INSERT INTO market_index_snapshots
               (trade_date,close,market_score,regime) VALUES(?,?,?,?)""",
            [(day, 100 + index, 60, "trend") for index, day in enumerate(dates)],
        )
        price_rows = []
        for index, day in enumerate(dates):
            values = {"A": 100 + index * 2, "P1": 100 + index * .5,
                      "P2": 100 + index * .5, "P3": 100 + index * .5}
            price_rows.extend(
                (symbol, "TWSE", day, value, value, value, value, 1_000_000)
                for symbol, value in values.items()
            )
        connection.executemany(
            """INSERT INTO daily_prices
               (symbol,market,trade_date,open,high,low,close,volume)
               VALUES(?,?,?,?,?,?,?,?)""",
            price_rows,
        )
    return dates


def test_backtest_uses_exact_future_market_sessions_and_relative_benchmarks(
    tmp_path: Path, monkeypatch,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    _seed_paths(database)
    monkeypatch.setattr(
        "app.short_term_ranking_backtest._select_signal_dates",
        lambda *_args, **_kwargs: (["2026-01-02"], {
            "frequency": "monthly", "available_signal_dates": 1,
            "evaluated_signal_dates": 1, "max_signal_dates": 120,
            "truncated_with_even_period_sampling": False,
        }),
    )
    monkeypatch.setattr(
        "app.short_term_ranking_backtest._factor_coverage_as_of",
        lambda _database, signal_date: _coverage(signal_date),
    )

    def decisions(_database, _context, signal_date, limit, *, historical_replay):
        assert historical_replay is True
        assert limit == 1
        return {
            "signal_date": signal_date.isoformat(), "market_mode": "trend",
            "candidate_universe_counts": {"eligible_on_common_signal_date": 100},
            "attention_rankings": [{
                "symbol": "A", "market": "TWSE", "name": "A",
                "industry": "technology", "close": 100,
                "attention_grade": "A", "attention_score": 80,
                "operation_status": "waiting_trigger",
                "latest_financial_available_date": "2026-01-02",
                "latest_revenue_available_date": "2026-01-01",
                "latest_valuation_date": "20260102",
                "institutional_flow": {"as_of": "2026-01-02"},
                "data_as_of": {"price": "2026-01-02"},
            }],
        }

    monkeypatch.setattr(
        "app.short_term_ranking_backtest.build_short_term_decisions", decisions
    )

    result = short_term_ranking_backtest(
        database, start_date="2026-01-02", end_date="2026-01-02", top_n=1,
    )

    outcome = result["outcomes"][0]["horizons"]["10"]
    assert outcome["target_date"] == "2026-01-16"
    assert outcome["return_percent"] == 20
    assert outcome["market_return_percent"] == 10
    assert outcome["market_excess_return_percent"] == 10
    assert outcome["industry_median_return_percent"] == 5
    assert outcome["industry_excess_return_percent"] == 15
    assert outcome["max_drawdown_percent"] == 0
    assert outcome["execution"]["entry_date"] == "2026-01-05"
    assert outcome["execution"]["entry_open"] == 102
    assert outcome["execution"]["exit_date"] == "2026-01-16"
    assert outcome["execution"]["gross_return_percent"] == 17.6471
    assert outcome["execution"]["net_return_percent"] == 16.8429
    assert outcome["execution"]["transaction_cost_drag_percent"] == 0.8042
    assert result["horizons"]["10"]["executable_items"] == 1
    assert result["horizons"]["10"]["average_executable_net_return_percent"] == 16.8429
    assert result["operation_status_breakdown"]["waiting_trigger"]["10"][
        "average_executable_net_return_percent"
    ] == 16.8429
    assert result["methodology"]["execution_price"] == "next-session open to horizon-session close"
    assert result["methodology"]["transaction_costs_bps"] == {
        "commission_each_side": 14.25,
        "sell_tax": 30.0,
        "slippage_each_side": 5.0,
    }
    assert result["lookahead_audit"]["status"] == "passed"
    assert result["effectiveness_assessment"]["verdict"] == "insufficient_data"


def test_backtest_refuses_dates_without_complete_factor_coverage(
    tmp_path: Path, monkeypatch,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    monkeypatch.setattr(
        "app.short_term_ranking_backtest._select_signal_dates",
        lambda *_args, **_kwargs: (["2025-12-31"], {
            "frequency": "monthly", "available_signal_dates": 1,
            "evaluated_signal_dates": 1, "max_signal_dates": 120,
            "truncated_with_even_period_sampling": False,
        }),
    )
    monkeypatch.setattr(
        "app.short_term_ranking_backtest._factor_coverage_as_of",
        lambda _database, signal_date: _coverage(signal_date, ready=2),
    )
    monkeypatch.setattr(
        "app.short_term_ranking_backtest.build_short_term_decisions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ranking must not run on incomplete data")
        ),
    )

    result = short_term_ranking_backtest(
        database, start_date="2025-12-31", end_date="2025-12-31",
        minimum_full_factor_symbols=50,
    )

    assert result["accepted_runs"] == 0
    assert result["total_ranked_items"] == 0
    assert result["skipped_signal_dates"][0]["reason"] == "insufficient_full_factor_coverage"
    assert result["effectiveness_assessment"]["verdict"] == "insufficient_data"


def test_historical_institution_query_is_bounded_to_signal_date(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO institutional_trades
               (symbol,market,trade_date,foreign_buy,foreign_sell,foreign_net,
                trust_buy,trust_sell,trust_net,source)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [
                ("A", "TWSE", "2026-01-02", 10, 0, 10, 0, 0, 0, "test"),
                ("A", "TWSE", "2026-01-05", 20, 0, 20, 0, 0, 0, "test"),
            ],
        )

    rows = database.get_institutional_trades(
        "A", 10, end_date="2026-01-02", market="TWSE"
    )

    assert [row["trade_date"] for row in rows] == ["2026-01-02"]


def test_historical_fundamental_assessment_excludes_signal_day_valuation(
    tmp_path: Path,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO daily_prices
               (symbol,market,trade_date,open,high,low,close,volume)
               VALUES(?,?,?,?,?,?,?,?)""",
            [
                ("A", "TWSE", "2026-01-01", 100, 100, 100, 100, 1_000),
                ("A", "TWSE", "2026-01-02", 100, 100, 100, 100, 1_000),
            ],
        )
        connection.executemany(
            """INSERT INTO valuations
               (symbol,market,valuation_date,pe_ratio,pb_ratio)
               VALUES(?,?,?,?,?)""",
            [
                ("A", "TWSE", "20260101", 10, 2),
                ("A", "TWSE", "20260102", 99, 9),
            ],
        )

    assessment = load_short_term_fundamental_assessment(
        database, "A", "TWSE", "2026-01-02", 100,
        end_of_day_data_cutoff="2026-01-01",
    )

    assert assessment["valuation_source_date"] == "20260101"
    assert assessment["reported_pe_ratio"] == 10


def test_research_page_exposes_ranking_backtest_controls():
    project_root = Path(__file__).resolve().parents[1]
    html = (project_root / "app" / "static" / "research.html").read_text(
        encoding="utf-8"
    )
    javascript = (project_root / "app" / "static" / "research.js").read_text(
        encoding="utf-8"
    )
    main_source = (project_root / "app" / "main.py").read_text(encoding="utf-8")

    assert 'id="runRankingBacktest"' in html
    assert "/research/jobs/short-term-ranking-backtest" in javascript
    assert "pollRankingBacktestJob" in javascript
    assert 'method: "POST"' in javascript
    assert '$("#rankingBacktestRows").innerHTML' in javascript
    assert 'id="rankingBacktestCommission"' in html
    assert 'id="rankingBacktestSellTax"' in html
    assert 'id="rankingBacktestSlippage"' in html
    assert "average_executable_net_return_percent" in javascript
    assert 'id="rankingOperationRows"' in html
    assert "operation_status_breakdown" in javascript
    assert '@app.get("/research/short-term-ranking-backtest")' in main_source
    assert '"/research/jobs/short-term-ranking-backtest"' in main_source


def test_ranking_backtest_job_returns_before_work_finishes(monkeypatch):
    from app.main import app

    started = Event()
    release = Event()

    def slow_backtest(*_args, **_kwargs):
        started.set()
        release.wait(2)
        return {"mode": "short_term_ranking_historical_replay", "horizons": {}}

    monkeypatch.setattr("app.main.short_term_ranking_backtest", slow_backtest)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/research/jobs/short-term-ranking-backtest",
                params={
                    "start_date": "2023-04-01",
                    "end_date": "2026-08-13",
                    "frequency": "monthly",
                },
            )
            assert response.status_code == 200
            job = response.json()["job"]
            assert job["status"] in {"running", "completed"}
            assert started.wait(.5)
            if job["status"] == "running":
                status = client.get(f"/research/jobs/{job['id']}").json()
                assert status["status"] == "running"
            release.set()
            for _ in range(50):
                status = client.get(f"/research/jobs/{job['id']}").json()
                if status["status"] == "completed":
                    break
                sleep(.01)
            assert status["status"] == "completed"
            assert status["result"]["mode"] == "short_term_ranking_historical_replay"
    finally:
        release.set()


def test_missing_industry_benchmark_is_not_positive_evidence():
    summary = {
        "3": {
            "matured_items": 30,
            "unique_signal_dates": 6,
            "average_market_excess_return_percent": 1.0,
            "average_industry_excess_return_percent": None,
        }
    }
    rank_breakdown = {
        "top_1_3": {"3": {"average_market_excess_return_percent": 2.0}},
        "rank_4_plus": {"3": {"average_market_excess_return_percent": 0.0}},
    }

    assessment = _effectiveness_assessment(summary, rank_breakdown, (3,), 30, 6)

    assert assessment["eligible_horizons"] == ["3"]
    assert assessment["supported_horizons"] == []
    assert assessment["details"][0]["industry_excess_positive"] is False
