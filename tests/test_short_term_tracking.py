import json
from datetime import date
from pathlib import Path

from app.database import Database
from app.short_term_tracking import (
    _signal_follow_up,
    capture_short_term_ranking_snapshot,
    published_short_term_decisions,
    ranking_publication_gate,
    short_term_ranking_tracking,
)


def test_signal_follow_up_separates_new_continued_and_expired_signals():
    previous = {
        "signal_date": "2026-08-13",
        "operation_ready_candidates": [
            {
                "symbol": "3029", "market": "TWSE", "name": "零壹",
                "operation_status": "ready", "operation_reason": "條件完成",
                "close": 111.5,
            },
            {
                "symbol": "2408", "market": "TWSE", "name": "南亞科",
                "operation_status": "ready_with_risk", "operation_reason": "條件完成但有風險",
                "close": 514,
            },
        ],
    }
    current = {
        "signal_date": "2026-08-14",
        "operation_ready_candidates": [
            {
                "symbol": "2603", "market": "TWSE", "name": "長榮",
                "operation_status": "ready", "operation_reason": "今日新觸發",
                "close": 219,
            },
            {
                "symbol": "2408", "market": "TWSE", "name": "南亞科",
                "operation_status": "ready_with_risk", "operation_reason": "仍然有效",
                "close": 515,
            },
        ],
        "tracked_candidate_statuses": [
            {
                "symbol": "3029", "market": "TWSE", "name": "零壹",
                "operation_status": "waiting_trigger",
                "operation_reason": "等待重新突破",
                "close": 111.5,
                "operation_gap": {"missing_count": 1},
            },
            {
                "symbol": "2408", "market": "TWSE", "name": "南亞科",
                "operation_status": "ready_with_risk",
                "operation_reason": "仍然有效",
                "close": 515,
            },
        ],
    }

    follow_up = _signal_follow_up(previous, current)

    assert follow_up["previous_signal_date"] == "2026-08-13"
    assert follow_up["current_signal_date"] == "2026-08-14"
    assert follow_up["new_trigger_symbols"] == ["2603"]
    assert [row["symbol"] for row in follow_up["continued_signals"]] == ["2408"]
    assert follow_up["continued_signals"][0]["lifecycle_status"] == "continued_with_risk"
    assert [row["symbol"] for row in follow_up["expired_signals"]] == ["3029"]
    assert follow_up["expired_signals"][0]["lifecycle_status"] == "waiting_retrigger"
    assert follow_up["expired_signals"][0]["reason"] == "等待重新突破"


def test_capture_persists_previous_ready_signal_follow_up(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda _database, result, *_args, **_kwargs: {
            "ready": True, "target_date": result["signal_date"], "markets": {}
        },
    )
    monkeypatch.setattr(
        "app.short_term_tracking.short_term_fundamental_candidates", lambda *_: []
    )

    def ranking(day: str, symbol: str, tracked: list[dict] | None = None) -> dict:
        ready = {
            "symbol": symbol, "market": "TWSE", "name": symbol,
            "industry": "測試", "close": 100, "attention_grade": "A",
            "attention_score": 80, "operation_status": "ready",
            "operation_reason": "條件完成", "trade_plan": {},
        }
        return {
            "signal_date": day, "as_of_date": day,
            "strategy_version": "short-term-3-10d-v2.5-pit-evidence",
            "market_mode": "trend", "market_data_aligned": True,
            "attention_rankings": [ready],
            "operation_ready_candidates": [ready],
            "tracked_candidate_statuses": tracked or [],
        }

    capture_short_term_ranking_snapshot(
        database,
        {"as_of": "2026-08-13", "index_close": 100},
        result=ranking("2026-08-13", "OLD"),
    )
    second = ranking(
        "2026-08-14",
        "NEW",
        [{
            "symbol": "OLD", "market": "TWSE", "name": "OLD", "close": 99,
            "operation_status": "waiting_trigger",
            "operation_reason": "等待重新突破",
        }],
    )
    capture_short_term_ranking_snapshot(
        database,
        {"as_of": "2026-08-14", "index_close": 101},
        result=second,
    )

    with database.connect() as connection:
        saved = json.loads(connection.execute(
            "SELECT result_json FROM short_term_ranking_runs WHERE signal_date='2026-08-14'"
        ).fetchone()[0])
    follow_up = saved["signal_follow_up"]
    assert follow_up["new_trigger_symbols"] == ["NEW"]
    assert follow_up["expired_signals"][0]["symbol"] == "OLD"
    assert follow_up["expired_signals"][0]["reason"] == "等待重新突破"


def test_snapshot_is_idempotent_and_forward_returns_mature_only_when_available(
    tmp_path: Path, monkeypatch,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    peers = [
        {"symbol": symbol, "market": "TWSE", "industry": "半導體",
         "latest_price_date": "2026-08-01"}
        for symbol in ("2330", "1111", "2222", "3333")
    ]
    monkeypatch.setattr(
        "app.short_term_tracking.short_term_fundamental_candidates",
        lambda *_: peers,
    )
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda *_args, **_kwargs: {"ready": True, "target_date": "2026-08-01", "markets": {}},
    )
    result = {
        "signal_date": "2026-08-01", "as_of_date": "2026-08-01",
        "strategy_version": "short-term-3-10d-v2.5-pit-evidence", "market_mode": "trend",
        "market_data_aligned": True,
        "attention_rankings": [{
            "symbol": "2330", "market": "TWSE", "name": "台積電", "industry": "半導體",
            "close": 100, "attention_grade": "A", "attention_score": 80,
            "attention_score_components": {"trend": 35},
            "operation_status": "waiting_trigger", "operation_reason": "等待突破",
            "operation_gap": {"missing_count": 1},
            "trade_plan": {"trigger_checks": {"breakout": {"passed": False}}},
            "data_as_of": {"price": "2026-08-01"},
        }],
    }
    context = {"index_close": 100, "as_of": "2026-08-01"}

    first = capture_short_term_ranking_snapshot(
        database, context, date(2026, 8, 1), result=result
    )
    second = capture_short_term_ranking_snapshot(
        database, context, date(2026, 8, 1), result=result
    )

    assert first["rows_written"] == 1
    assert second["rows_written"] == 0
    assert second["publication_status"] == "already_published"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM short_term_ranking_runs"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM short_term_ranking_run_items"
        ).fetchone()[0] == 1
        price_rows = []
        dates = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
        closes = {
            "2330": [100, 101, 102, 106],
            "1111": [100, 100, 101, 102],
            "2222": [100, 101, 102, 103],
            "3333": [100, 102, 103, 104],
        }
        for symbol, values in closes.items():
            price_rows.extend((symbol, "TWSE", day, value, value, value, value, 1000)
                              for day, value in zip(dates, values))
        connection.executemany(
            """INSERT INTO daily_prices
               (symbol,market,trade_date,open,high,low,close,volume)
               VALUES(?,?,?,?,?,?,?,?)""",
            price_rows,
        )
        connection.executemany(
            "INSERT INTO market_index_snapshots(trade_date,close) VALUES(?,?)",
            zip(dates, [100, 101, 102, 103]),
        )

    tracking = short_term_ranking_tracking(database)

    horizon3 = tracking["outcomes"][0]["horizons"]["3"]
    assert horizon3["matured"] is True
    assert horizon3["return_percent"] == 6.0
    assert horizon3["market_excess_return_percent"] == 3.0
    assert horizon3["industry_median_return_percent"] == 3.0
    assert horizon3["industry_excess_return_percent"] == 3.0
    assert tracking["horizons"]["3"]["matured_signals"] == 1
    assert tracking["horizons"]["3"]["unique_signal_dates"] == 1
    assert tracking["horizons"]["5"]["matured_signals"] == 0
    assert tracking["horizons"]["5"]["pending_signals"] == 1
    assert tracking["effectiveness_assessment"]["verdict"] == "insufficient_data"
    assert tracking["effectiveness_assessment"]["formal_validation_allowed"] is False


def test_partial_exchange_rollover_is_not_publishable(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO daily_prices
               (symbol,market,trade_date,open,high,low,close,volume)
               VALUES(?,?,?,?,?,?,?,?)""",
            [
                ("1101", "TWSE", "2026-08-10", 10, 10, 10, 10, 1000),
                ("1102", "TWSE", "2026-08-11", 10, 10, 10, 10, 1000),
                ("3101", "TPEx", "2026-08-10", 10, 10, 10, 10, 1000),
                ("3102", "TPEx", "2026-08-10", 10, 10, 10, 10, 1000),
            ],
        )

    gate = ranking_publication_gate(
        database,
        {"signal_date": "2026-08-10", "market_data_as_of": "2026-08-11"},
        {"as_of": "2026-08-11"},
    )

    assert gate["ready"] is False
    assert gate["target_date"] == "2026-08-11"
    assert gate["markets"]["TWSE"]["exact_date_coverage_percent"] == 50.0
    assert gate["markets"]["TPEx"]["exact_date_coverage_percent"] == 0.0
    assert "股票與大盤資料日期不一致" in gate["blocking_reasons"]


def test_incomplete_live_data_keeps_last_valid_published_list(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    valid = {
        "signal_date": "2026-08-10", "as_of_date": "2026-08-10",
        "strategy_version": "short-term-3-10d-v2.5-pit-evidence", "market_mode": "range",
        "market_data_aligned": True,
        "attention_rankings": [{
            "symbol": "OLD", "market": "TWSE", "name": "有效榜單", "industry": "測試",
            "close": 100, "attention_grade": "A", "attention_score": 80,
            "operation_status": "waiting_trigger", "trade_plan": {},
        }],
        "operation_ready_candidates": [], "closest_operation_candidates": [],
    }
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda *_args, **_kwargs: {"ready": True, "target_date": "2026-08-10", "markets": {}},
    )
    monkeypatch.setattr(
        "app.short_term_tracking.short_term_fundamental_candidates", lambda *_: []
    )
    capture_short_term_ranking_snapshot(
        database, {"as_of": "2026-08-10", "index_close": 100}, result=valid
    )

    incomplete = {
        **valid, "signal_date": "2026-08-10", "market_data_as_of": "2026-08-11",
        "market_data_aligned": False,
        "attention_rankings": [{**valid["attention_rankings"][0], "symbol": "UNSTABLE"}],
    }
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda *_args, **_kwargs: {
            "ready": False, "target_date": "2026-08-11", "markets": {},
            "blocking_reasons": ["股票與大盤資料日期不一致"],
        },
    )

    published = published_short_term_decisions(
        database, {"as_of": "2026-08-11"}, date(2026, 8, 11), result=incomplete
    )

    assert published["publication_status"] == "held_previous"
    assert published["attention_rankings"][0]["symbol"] == "OLD"
    assert published["live_candidate_signal_date"] == "2026-08-10"


def test_published_decisions_reuse_same_signal_date_snapshot(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    saved = {
        "signal_date": "2026-08-10", "as_of_date": "2026-08-10",
        "strategy_version": "short-term-3-10d-v2.5-pit-evidence",
        "market_mode": "range", "market_data_aligned": True,
        "attention_rankings": [{
            "symbol": "2330", "market": "TWSE", "name": "台積電",
            "industry": "半導體", "close": 100, "attention_grade": "A",
            "attention_score": 80, "operation_status": "waiting_trigger",
            "trade_plan": {},
        }],
    }
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda *_args, **_kwargs: {"ready": True, "target_date": "2026-08-10", "markets": {}},
    )
    monkeypatch.setattr(
        "app.short_term_tracking.short_term_fundamental_candidates", lambda *_: []
    )
    capture_short_term_ranking_snapshot(
        database, {"as_of": "2026-08-10", "index_close": 100}, result=saved
    )
    monkeypatch.setattr(
        "app.short_term_tracking.build_short_term_decisions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must use snapshot")),
    )

    published = published_short_term_decisions(
        database, {"as_of": "2026-08-10"}, date(2026, 8, 10), limit=10
    )

    assert published["publication_status"] == "ready"
    assert published["ranking_is_stale"] is False
    assert published["attention_rankings"][0]["symbol"] == "2330"


def test_published_snapshot_revalidates_resolved_data_pending_status(
    tmp_path: Path, monkeypatch
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    saved = {
        "signal_date": "2026-08-13",
        "as_of_date": "2026-08-14",
        "strategy_version": "short-term-3-10d-v2.5-pit-evidence",
        "market_mode": "trend",
        "market_data_aligned": True,
        "attention_rankings": [{
            "symbol": "2330", "market": "TWSE", "name": "台積電",
            "industry": "半導體", "close": 100, "attention_grade": "A",
            "attention_score": 80, "operation_status": "waiting_trigger",
            "trade_plan": {},
        }],
        "fundamental_data_pending": [{
            "symbol": "2344", "market": "TWSE", "name": "華邦電",
            "close": 177, "latest_price_date": "2026-08-13",
            "fundamental_snapshot": {"status": "data_pending"},
        }],
    }
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda *_args, **_kwargs: {
            "ready": True, "target_date": "2026-08-13", "markets": {}
        },
    )
    monkeypatch.setattr(
        "app.short_term_tracking.short_term_fundamental_candidates", lambda *_: []
    )
    capture_short_term_ranking_snapshot(
        database, {"as_of": "2026-08-13", "index_close": 100}, result=saved
    )
    monkeypatch.setattr(
        "app.short_term_tracking.load_short_term_fundamental_assessment",
        lambda *_args, **_kwargs: {
            "status": "pass", "passed": True,
            "financial_date": "2026-06-30",
        },
    )

    published = published_short_term_decisions(
        database, {"as_of": "2026-08-13"}, date(2026, 8, 14), limit=10
    )

    assert published["fundamental_data_pending"] == []
    assert published["resolved_data_pending_symbols"] == ["2344"]
    assert published["attention_rankings"][0]["symbol"] == "2330"


def test_new_signal_date_creates_immutable_run_and_records_turnover(tmp_path: Path, monkeypatch):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda _database, result, *_args, **_kwargs: {
            "ready": True, "target_date": result["signal_date"], "markets": {}
        },
    )
    monkeypatch.setattr(
        "app.short_term_tracking.short_term_fundamental_candidates", lambda *_: []
    )

    def result(day, symbols):
        return {
            "signal_date": day, "as_of_date": day,
            "strategy_version": "short-term-3-10d-v2.5-pit-evidence", "market_mode": "trend",
            "market_data_aligned": True, "operation_ready_candidates": [],
            "closest_operation_candidates": [],
            "attention_rankings": [{
                "symbol": symbol, "market": "TWSE", "name": symbol, "industry": "測試",
                "close": 100, "attention_grade": "B", "attention_score": 60 - rank,
                "operation_status": "waiting_trigger", "trade_plan": {},
                "ranking_evidence": ["趨勢偏多"],
            } for rank, symbol in enumerate(symbols)],
        }

    capture_short_term_ranking_snapshot(
        database, {"as_of": "2026-08-10", "index_close": 100}, result=result("2026-08-10", ["A", "B"])
    )
    second = capture_short_term_ranking_snapshot(
        database, {"as_of": "2026-08-11", "index_close": 101}, result=result("2026-08-11", ["B", "C"])
    )

    assert second["turnover_percent"] == 50.0
    assert [row["symbol"] for row in second["changes"]["entered"]] == ["C"]
    assert [row["symbol"] for row in second["changes"]["exited"]] == ["A"]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM short_term_ranking_runs").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM short_term_ranking_run_items").fetchone()[0] == 4


def test_incomplete_current_day_bootstraps_previous_complete_signal_date(
    tmp_path: Path, monkeypatch,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    current = {
        "signal_date": "2026-08-10", "as_of_date": "2026-08-11",
        "strategy_version": "short-term-3-10d-v2.5-pit-evidence", "market_data_as_of": "2026-08-11",
        "market_data_aligned": False, "attention_rankings": [],
    }
    historical = {
        "signal_date": "2026-08-10", "as_of_date": "2026-08-10",
        "strategy_version": "short-term-3-10d-v2.5-pit-evidence", "market_mode": "trend",
        "market_data_as_of": "2026-08-10", "market_data_aligned": True,
        "attention_rankings": [{
            "symbol": "2330", "market": "TWSE", "name": "台積電", "industry": "半導體",
            "close": 100, "attention_grade": "A", "attention_score": 80,
            "operation_status": "waiting_trigger", "trade_plan": {},
        }],
    }
    monkeypatch.setattr(
        "app.short_term_tracking.ranking_publication_gate",
        lambda _database, result, context, **_kwargs: {
            "ready": result.get("market_data_aligned") is True,
            "target_date": context.get("as_of"), "markets": {},
            "blocking_reasons": [] if result.get("market_data_aligned") else ["日期不一致"],
        },
    )
    monkeypatch.setattr(
        "app.short_term_tracking._historical_market_context",
        lambda *_args, **_kwargs: {"as_of": "2026-08-10", "index_close": 100},
    )
    monkeypatch.setattr(
        "app.short_term_tracking.build_short_term_decisions",
        lambda *_args, **_kwargs: historical,
    )
    monkeypatch.setattr(
        "app.short_term_tracking.short_term_fundamental_candidates", lambda *_: []
    )

    capture = capture_short_term_ranking_snapshot(
        database, {"as_of": "2026-08-11", "index_close": 101}, result=current
    )

    assert capture["publication_status"] == "held_previous"
    assert capture["bootstrap"]["publication_status"] == "published"
    with database.connect() as connection:
        assert connection.execute("SELECT signal_date FROM short_term_ranking_runs").fetchone()[0] == "2026-08-10"
