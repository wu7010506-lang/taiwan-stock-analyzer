from datetime import date, timedelta
from pathlib import Path

from app.database import Database
from app.domain import Instrument
from app.short_term_decision import (
    _base_candidates,
    _iso_date,
    _research_priority_score,
    assess_short_term_position,
    build_short_term_decisions,
)
from app.short_term_fundamentals import (
    assess_short_term_fundamentals,
    load_short_term_fundamental_assessment,
)


class _Database:
    def get_prices(self, *args, **kwargs):
        rows = [{"trade_date": (date(2026, 5, 1) + timedelta(days=index)).isoformat(),
                 "close": 95, "high": 96, "low": 94, "open": 95,
                 "volume": 100_000} for index in range(60)]
        rows[5]["high"] = 120
        rows[-1].update({"close": 100, "high": 101, "low": 97, "open": 98,
                         "volume": 200_000})
        return rows


def _candidate():
    return {"symbol": "2330", "market": "TWSE", "name": "測試", "industry": "電子",
            "close": 100, "latest_price_date": "2026-07-31",
            "latest_financial_date": "2026-06-30", "average_turnover_20": 10_000_000}


def _indicators(**overrides):
    values = {"close": 100, "atr_14": 2, "rsi_14": 50, "adx_14": 25,
              "plus_di_14": 30, "minus_di_14": 20, "natr_14": 2, "mfi_14": 55,
              "trend_confirmation": True, "breakout_20d": True,
              "breakout_level_20d": 96, "volume_ratio_20": 2,
              "volume_confirmation_20d": True, "bollinger_lower": 95,
              "sma_5": 99, "sma_10": 98, "sma_20": 97, "sma_60": 96,
              "return_1d_percent": 2, "return_5d_percent": 3,
              "return_10d_percent": 5, "return_20d_percent": 8,
              "volume_ratio_5": 1.8, "macd_histogram_change": .2}
    values.update(overrides)
    return {"indicators": values}


def test_roc_market_date_is_aligned_to_iso_signal_date():
    assert _iso_date("115/08/10") == "2026-08-10"
    assert _iso_date("1150810") == "2026-08-10"


def test_defensive_market_does_not_hide_a_complete_breakout(monkeypatch):
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: ([_candidate()], []))
    monkeypatch.setattr("app.short_term_decision.calculate_technical_indicators", lambda _: _indicators())

    result = build_short_term_decisions(
        _Database(), {"as_of": "2026-07-31", "market_score": 20, "index_change_20d": -8},
        date(2026, 8, 2),
    )

    assert result["fundamental_gate"]["passed"] == 1
    decision = result["decisions"][0]
    assert decision["action"] == "analysis_pass"
    assert decision["setup"] == "confirmed_breakout"
    assert decision["market_mode"] == "defensive"
    assert decision["market_position_cap_percent"] == 2.5
    assert 0 <= decision["research_priority_score"] <= 100
    assert isinstance(decision["ranking_evidence"], list)
    assert isinstance(decision["ranking_risks"], list)
    assert "observation_rankings" in result
    assert "execution_candidates" in result
    assert result["execution_candidates"] == []
    assert decision["operation_status"] == "ready"
    assert result["operation_ready_candidates"][0]["symbol"] == "2330"
    assert decision["attention_grade"] in {"A", "B", "C"}
    assert result["observation_rankings"][0]["observation_status"]
    assert "closest_operation_candidates" in result


def test_trend_breakout_is_detected_but_cannot_open_a_position(monkeypatch):
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: ([_candidate()], []))
    monkeypatch.setattr("app.short_term_decision.calculate_technical_indicators", lambda _: _indicators())

    result = build_short_term_decisions(
        _Database(), {"as_of": "2026-07-31", "market_score": 60, "index_change_20d": 0},
        date(2026, 8, 2),
    )
    decision = result["decisions"][0]

    assert decision["action"] == "analysis_pass"
    assert decision["setup"] == "confirmed_breakout"
    assert decision["execution"].startswith("訊號日收盤後")
    assert decision["invalidation_price"] == 97
    assert result["execution_governance"]["new_entries_enabled"] is False


def test_fundamental_gate_uses_financial_availability_date(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "測試", "TWSE")])
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume)
               VALUES('2330','TWSE',?,?,?,?,?,?)""",
            [((date(2026, 7, 31) - timedelta(days=offset)).isoformat(), 100, 101, 99, 100, 100_000)
             for offset in range(60)],
        )
        connection.executemany(
            """INSERT INTO financial_snapshots(symbol,market,fiscal_year,fiscal_quarter,report_type,
               total_assets,total_liabilities,operating_income,net_income,eps,free_cash_flow,
               statement_date,source)
               VALUES('2330','TWSE',?,?,?,?,?,?,?,?,?,?,?)""",
            [(2025, 1, "finmind", 1000, 400, 120, 100, 1, 100, "2025-03-31", "FinMind / MOPS"),
             (2025, 2, "finmind", 1000, 400, 120, 100, 1, 100, "2025-06-30", "FinMind / MOPS"),
             (2025, 3, "finmind", 1000, 400, 120, 100, 1, 100, "2025-09-30", "FinMind / MOPS"),
             (2025, 4, "finmind", 1000, 400, 120, 100, 1, 100, "2025-12-31", "FinMind / MOPS"),
             (2026, 1, "finmind", 1000, 400, 120, 100, 1, 100, "2026-06-30", "FinMind / MOPS")],
        )
        connection.execute(
            "INSERT INTO valuations(symbol,market,valuation_date,pe_ratio) VALUES('2330','TWSE','20260731',20)"
        )
        connection.execute(
            """INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent)
               VALUES('2330','TWSE','2026-06',1000,5)"""
        )

    candidates = _base_candidates(database, date(2026, 8, 2))

    assert candidates[0]["latest_financial_date"] == "2025-12-31"
    assert candidates[0]["latest_financial_available_date"] == "2026-03-31"


def test_official_extract_date_does_not_bypass_lag_before_local_observation(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2103", "台橡", "TWSE")])
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume)
               VALUES('2103','TWSE',?,?,?,?,?,?)""",
            [((date(2026, 8, 11) - timedelta(days=offset)).isoformat(), 28.65, 29, 27.5, 28.65, 1_000_000)
             for offset in range(60)],
        )
        connection.executemany(
            """INSERT INTO financial_snapshots(
                   symbol,market,fiscal_year,fiscal_quarter,report_type,revenue,
                   operating_income,net_income,eps,total_assets,total_liabilities,
                   free_cash_flow,statement_date,published_date,source_as_of_date,source,fetched_at)
               VALUES('2103','TWSE',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (2025, 2, "finmind", 1000, 100, 80, .1, 48_000, 24_000, 100, "2025-06-30", None, None, "FinMind / MOPS", "2026-07-22 08:00:00"),
                (2025, 3, "finmind", 1000, 100, 80, .1, 48_000, 24_000, 100, "2025-09-30", None, None, "FinMind / MOPS", "2026-07-22 08:00:00"),
                (2025, 4, "finmind", 1000, 100, 80, .1, 48_000, 24_000, 100, "2025-12-31", None, None, "FinMind / MOPS", "2026-07-22 08:00:00"),
                (2026, 1, "finmind", 10_000, 651, 502, .53, 45_000, 23_000, 100, "2026-03-31", None, None, "FinMind / MOPS", "2026-07-22 08:00:00"),
                (2026, 2, "ci", 22_212, 2_462, 1_867, 2.26, 48_019, 24_135, None, "2026-06-30", None, "2026-08-11", "TWSE official OpenAPI", "2026-08-12 08:00:00"),
            ],
        )
        connection.execute(
            """INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume)
               VALUES('2103','TWSE','2026-08-10',27.5,27.5,27.5,27.5,1000000)
               ON CONFLICT(symbol,market,trade_date) DO UPDATE SET close=excluded.close"""
        )
        connection.execute(
            """INSERT INTO valuations(symbol,market,valuation_date,pe_ratio,pb_ratio)
               VALUES('2103','TWSE','20260810',11.04,1.03)"""
        )
        connection.execute(
            """INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent)
               VALUES('2103','TWSE','2026-07',3642000000,32.52)"""
        )

    before_lag = load_short_term_fundamental_assessment(
        database, "2103", "TWSE", "2026-08-11", 28.65
    )
    after_observed = load_short_term_fundamental_assessment(
        database, "2103", "TWSE", "2026-08-12", 28.65
    )
    after_lag = load_short_term_fundamental_assessment(
        database, "2103", "TWSE", "2026-08-14", 28.65
    )

    assert before_lag["financial_date"] == "2026-03-31"
    assert after_observed["financial_date"] == "2026-06-30"
    assert after_observed["financial_available_date"] == "2026-08-12"
    assert after_observed["financial_availability_method"] == "official_row_first_observed"
    assert after_lag["financial_date"] == "2026-06-30"
    assert after_lag["financial_available_date"] == "2026-08-12"
    assert after_lag["ttm_eps"] == 2.46
    assert after_lag["passed"] is True


def test_official_valuation_period_proves_matching_financial_quarter_was_available(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2408", "南亞科", "TWSE")])
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume)
               VALUES('2408','TWSE','2026-08-11',521.1908,521.1908,521.1908,521.1908,1000000)"""
        )
        connection.executemany(
            """INSERT INTO financial_snapshots(
                   symbol,market,fiscal_year,fiscal_quarter,report_type,revenue,
                   operating_income,net_income,eps,total_assets,total_liabilities,
                   free_cash_flow,statement_date,published_date,source_as_of_date,source)
               VALUES('2408','TWSE',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (2025, 1, "finmind", 7_188, -3_155, -1_941, -.63, 214_737, 50_866, 100, "2025-03-31", None, None, "FinMind / MOPS"),
                (2025, 2, "finmind", 10_526, -4_501, -4_102, -1.32, 203_745, 49_079, 100, "2025-06-30", None, None, "FinMind / MOPS"),
                (2025, 3, "finmind", 18_779, 1_119, 1_563, .50, 202_563, 45_220, 100, "2025-09-30", None, None, "FinMind / MOPS"),
                (2025, 4, "finmind", 30_094, 11_781, 11_092, 3.58, 208_453, 37_914, 100, "2025-12-31", None, None, "FinMind / MOPS"),
                (2026, 1, "ci", 49_087, 30_111, 26_059, 8.41, 240_968, 47_931, None, "2026-03-31", None, None, "TWSE official OpenAPI"),
                (2026, 2, "ci", 131_636, 90_938, 76_252, 23.38, 387_758, 65_060, None, "2026-06-30", None, "2026-08-12", "TWSE official OpenAPI"),
            ],
        )
        connection.execute(
            """INSERT INTO valuations(
                   symbol,market,valuation_date,close_price,pe_ratio,pb_ratio,
                   dividend_yield,financial_period)
               VALUES('2408','TWSE','20260811',521.1908,18.98,5.23,.28,'115/2')"""
        )
        connection.execute(
            """INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent)
               VALUES('2408','TWSE','2026-07',12000000000,25)"""
        )

    assessment = load_short_term_fundamental_assessment(
        database, "2408", "TWSE", "2026-08-11", 521.1908
    )

    assert assessment["financial_date"] == "2026-06-30"
    assert assessment["financial_available_date"] == "2026-08-11"
    assert assessment["ttm_eps"] == 27.46
    assert assessment["pe_cross_check_difference_percent"] == 0
    assert assessment["requires_financial_refresh"] is False


def test_official_valuation_period_blocks_when_matching_financial_row_is_missing(
    tmp_path: Path,
):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("5475", "德宏", "TPEx")])
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO daily_prices(
                   symbol,market,trade_date,open,high,low,close,volume)
               VALUES('5475','TPEx','2026-08-14',40,40,40,40,1000000)"""
        )
        connection.executemany(
            """INSERT INTO financial_snapshots(
                   symbol,market,fiscal_year,fiscal_quarter,report_type,revenue,
                   operating_income,net_income,eps,total_assets,total_liabilities,
                   free_cash_flow,statement_date,source)
               VALUES('5475','TPEx',?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (2025, 2, "finmind", 100, 20, 10, 1, 100, 20, 10,
                 "2025-06-30", "FinMind / MOPS"),
                (2025, 3, "finmind", 100, 20, 10, 1, 100, 20, 10,
                 "2025-09-30", "FinMind / MOPS"),
                (2025, 4, "finmind", 100, 20, 10, 1, 100, 20, 10,
                 "2025-12-31", "FinMind / MOPS"),
                (2026, 1, "finmind", 100, 20, 10, 1, 100, 20, 10,
                 "2026-03-31", "FinMind / MOPS"),
            ],
        )
        connection.execute(
            """INSERT INTO valuations(
                   symbol,market,valuation_date,close_price,pe_ratio,pb_ratio,
                   dividend_yield,financial_period)
               VALUES('5475','TPEx','20260814',40,10,2,1,'115Q2')"""
        )
        connection.execute(
            """INSERT INTO monthly_revenues(
                   symbol,market,revenue_month,revenue,yoy_percent)
               VALUES('5475','TPEx','2026-07',100,10)"""
        )

    assessment = load_short_term_fundamental_assessment(
        database, "5475", "TPEx", "2026-08-14", 40
    )

    assert assessment["status"] == "data_pending"
    assert assessment["requires_financial_refresh"] is True
    assert "official_valuation_financial_period_missing" in assessment["blocking_codes"]


def test_short_position_exits_next_open_after_ten_sessions():
    prices = [{"trade_date": f"2026-07-{day:02d}", "close": 100} for day in range(1, 11)]
    decision = assess_short_term_position(
        {"close": 100, "purchase_date": "2026-07-01", "stop_loss": 90, "target_price": 120},
        prices, date(2026, 7, 31),
    )

    assert decision["action"] == "exit_next_open"
    assert decision["reasons"] == ["short_term_time_exit"]


def test_mean_reversion_setup_is_detected_but_cannot_open_a_position(monkeypatch):
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: ([_candidate()], []))
    monkeypatch.setattr(
        "app.short_term_decision.calculate_technical_indicators",
        lambda _: _indicators(rsi_14=20, adx_14=10, bollinger_lower=101,
                              trend_confirmation=False, breakout_20d=False,
                              volume_confirmation_20d=False),
    )

    result = build_short_term_decisions(_Database(), {"market_score": 50, "index_change_20d": 0}, date(2026, 8, 2))
    decision = result["decisions"][0]

    assert decision["action"] == "no_trade"
    assert decision["setup"] == "none"
    assert result["strategy_version"] == "short-term-3-10d-v2.5-pit-evidence"


def test_fundamental_gate_rejects_high_pe_and_declining_revenue(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("3441", "聯一光電", "TPEx")])
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume)
               VALUES('3441','TPEx',?,?,?,?,?,?)""",
            [((date(2026, 8, 2) - timedelta(days=offset)).isoformat(), 90, 91, 89, 90, 100_000)
             for offset in range(60)],
        )
        connection.executemany(
            """INSERT INTO financial_snapshots(symbol,market,fiscal_year,fiscal_quarter,report_type,
               total_assets,total_liabilities,net_income,free_cash_flow,statement_date)
               VALUES('3441','TPEx',?,?,?,?,?,?,?,?)""",
            [(2025, quarter, "test", 1000, 400, 10, 10, f"2025-{quarter * 3:02d}-28")
             for quarter in range(1, 5)],
        )
        connection.execute(
            "INSERT INTO valuations(symbol,market,valuation_date,pe_ratio) VALUES('3441','TPEx','20260801',78.6)"
        )
        connection.execute(
            """INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent)
               VALUES('3441','TPEx','2026-06',1000,-5)"""
        )

    assert _base_candidates(database, date(2026, 8, 2)) == []


def test_fundamental_gate_rejects_missing_net_income_or_free_cash_flow(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("9999", "缺值測試", "TWSE")])
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume)
               VALUES('9999','TWSE',?,?,?,?,?,?)""",
            [((date(2026, 8, 2) - timedelta(days=offset)).isoformat(), 50, 51, 49, 50, 200_000)
             for offset in range(60)],
        )
        connection.executemany(
            """INSERT INTO financial_snapshots(symbol,market,fiscal_year,fiscal_quarter,report_type,
               total_assets,total_liabilities,net_income,free_cash_flow,statement_date)
               VALUES('9999','TWSE',?,?,?,?,?,?,?,?)""",
            [(2025, quarter, "test", 1000, 400, None, 10, f"2025-{quarter * 3:02d}-28")
             for quarter in range(1, 5)],
        )
        connection.execute(
            "INSERT INTO valuations(symbol,market,valuation_date,pe_ratio) VALUES('9999','TWSE','20260801',20)"
        )
        connection.execute(
            """INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent)
               VALUES('9999','TWSE','2026-06',1000,5)"""
        )

    assert _base_candidates(database, date(2026, 8, 2)) == []


def test_fundamental_gate_rejects_high_pe_when_core_earnings_are_weak(tmp_path: Path):
    """A technical breakout must not override expensive, low-quality earnings."""
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    database.upsert_instruments([Instrument("2302", "麗正", "TWSE")])
    with database.connect() as connection:
        price_rows = []
        for offset in range(60):
            trade_date = date(2026, 8, 11) - timedelta(days=offset)
            close = 46.05 if offset == 0 else 42.5 if offset == 1 else 40
            price_rows.append((trade_date.isoformat(), close, close, close, close, 200_000))
        connection.executemany(
            """INSERT INTO daily_prices(symbol,market,trade_date,open,high,low,close,volume)
               VALUES('2302','TWSE',?,?,?,?,?,?)""",
            price_rows,
        )
        connection.executemany(
            """INSERT INTO financial_snapshots(
                   symbol,market,fiscal_year,fiscal_quarter,report_type,revenue,
                   operating_income,net_income,eps,total_assets,total_liabilities,
                   free_cash_flow,statement_date,source)
               VALUES('2302','TWSE',?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (2025, 1, "finmind", 193_476_000, 28_941_000, -7_554_000, -.05,
                 2_600_000_000, 900_000_000, -159_545_000, "2025-03-31", "FinMind / MOPS"),
                (2025, 2, "finmind", 216_525_000, 34_821_000, 11_395_000, .07,
                 2_600_000_000, 900_000_000, -161_248_000, "2025-06-30", "FinMind / MOPS"),
                (2025, 3, "finmind", 224_423_000, 30_059_000, 62_235_000, .38,
                 2_600_000_000, 900_000_000, -151_579_000, "2025-09-30", "FinMind / MOPS"),
                (2025, 4, "finmind", 211_344_000, 23_343_000, 15_797_000, .09,
                 2_600_000_000, 900_000_000, -112_750_000, "2025-12-31", "FinMind / MOPS"),
                (2026, 1, "finmind", 216_325_000, 16_066_000, 41_461_000, .25,
                 2_680_414_000, 894_283_000, 38_432_000, "2026-03-31", "FinMind / MOPS"),
            ],
        )
        connection.execute(
            """INSERT INTO valuations(
                   symbol,market,valuation_date,pe_ratio,pb_ratio,dividend_yield)
               VALUES('2302','TWSE','20260810',53.8,3.96,.82)"""
        )
        connection.execute(
            """INSERT INTO monthly_revenues(symbol,market,revenue_month,revenue,yoy_percent)
               VALUES('2302','TWSE','2026-07',122214000,81.16)"""
        )

    assessment = load_short_term_fundamental_assessment(
        database, "2302", "TWSE", "2026-08-11", 46.05
    )

    assert assessment["ttm_eps"] == .79
    assert assessment["pe_ratio"] == 58.2911
    assert assessment["reported_pe_ratio"] == 53.8
    assert assessment["operating_income_yoy_percent"] == -44.4871
    assert assessment["core_earnings_ratio_percent"] == 38.7497
    assert assessment["ttm_free_cash_flow"] == 85_227_000
    assert assessment["passed"] is False
    assert "high_pe_operating_income_decline" in assessment["blocking_codes"]
    assert "high_pe_low_core_earnings_share" in assessment["blocking_codes"]
    assert _base_candidates(database, date(2026, 8, 11)) == []


def test_rr_failure_blocks_operation_but_does_not_define_attention_grade(monkeypatch):
    candidate = _candidate()
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: ([candidate], []))
    monkeypatch.setattr("app.short_term_decision.calculate_technical_indicators", lambda _: _indicators())

    class NoResistanceDatabase(_Database):
        def get_prices(self, *args, **kwargs):
            rows = super().get_prices(*args, **kwargs)
            rows[5]["high"] = 96
            return rows

    result = build_short_term_decisions(
        NoResistanceDatabase(),
        {"as_of": "2026-07-31", "market_score": 50, "index_change_20d": 0},
        date(2026, 8, 2),
    )

    decision = result["decisions"][0]
    assert decision["attention_grade"] == "B"
    assert decision["candidate_grade"] == "B"
    assert decision["operation_status"] == "reject_rr"
    assert decision["action"] == "no_trade"
    assert decision["setup"] == "confirmed_breakout_rr_insufficient"
    assert "次優先關注" in decision["observation_status"]
    assert decision not in result["analysis_pass_candidates"]


def test_industry_limit_is_hard_and_peer_context_excludes_subject(monkeypatch):
    candidates = [_candidate() | {"symbol": f"90{index}", "name": f"測試{index}"}
                  for index in range(4)]
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: (candidates, []))
    monkeypatch.setattr("app.short_term_decision.calculate_technical_indicators", lambda _: _indicators())

    result = build_short_term_decisions(
        _Database(), {"as_of": "2026-07-31", "market_score": 60, "index_change_20d": 0},
        date(2026, 8, 2), limit=10,
    )

    assert len(result["observation_rankings"]) == 3
    assert result["industry_concentration_policy"]["hard_limit"] is True
    assert max(result["industry_concentration_policy"]["actual_counts"].values()) == 3
    context = result["observation_rankings"][0]["industry_context"]
    assert context["subject_excluded"] is True
    assert context["constituent_count"] == 3


def test_macd_confirmation_does_not_duplicate_trend_score():
    base = {
        "indicators": {"sma_5": 10, "sma_10": 9, "sma_20": 8, "sma_60": 7,
                       "relative_market_20d_percent": 2, "return_1d_percent": 1,
                       "macd_histogram_change": 1},
        "trade_plan": {"reference_entry": 10, "breakout_level": 9,
                       "volume_check": {"result": "通過"}, "core_blocking_reasons": [],
                       "planned_target_independent_from_rr": True,
                       "cost_adjusted_risk_reward": 2, "required_rr": 2,
                       "soft_risks": []},
        "average_turnover_20": 20_000_000,
        "institutional_flow": {}, "event_risk": {}, "market_mode": "range",
    }
    changed = {**base, "indicators": {**base["indicators"], "macd_histogram_change": -1}}

    assert _research_priority_score(base)[0] == _research_priority_score(changed)[0]


def test_untriggered_or_provisional_rr_does_not_change_attention_score():
    base = {
        "indicators": {"sma_5": 10, "sma_10": 9, "sma_20": 8, "sma_60": 7,
                       "relative_market_20d_percent": 3,
                       "relative_industry_5d_percent": 2,
                       "relative_industry_10d_percent": 2},
        "trade_plan": {"core_blocking_reasons": [], "cost_adjusted_risk_reward": 3,
                       "required_rr": 2, "soft_risks": []},
        "average_turnover_20": 30_000_000,
        "institutional_flow": {}, "event_risk": {}, "market_mode": "range",
    }
    not_triggered = {**base, "trade_plan": {
        **base["trade_plan"], "core_blocking_reasons": ["尚未突破"],
        "cost_adjusted_risk_reward": 0.2,
    }}

    assert _research_priority_score(base)[0] == _research_priority_score(not_triggered)[0]


def test_closest_operation_lists_structured_missing_conditions(monkeypatch):
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: ([_candidate()], []))
    monkeypatch.setattr(
        "app.short_term_decision.calculate_technical_indicators",
        lambda _: _indicators(breakout_20d=False, breakout_level_20d=105,
                              volume_ratio_20=1.0, volume_confirmation_20d=False),
    )

    result = build_short_term_decisions(
        _Database(), {"as_of": "2026-07-31", "market_score": 60, "index_change_20d": 0},
        date(2026, 8, 2),
    )

    closest = result["closest_operation_candidates"][0]
    keys = {check["key"] for check in closest["operation_gap"]["missing_checks"]}
    assert keys == {"breakout", "volume"}
    assert closest["operation_gap"]["missing_count"] == 2
    assert closest["operation_gap"]["rr_is_provisional"] is True


def test_closest_operation_only_uses_attention_list_and_prioritizes_missing_condition(monkeypatch):
    candidates = [
        _candidate() | {
            "symbol": "TOP1", "industry": "industry-1", "stub_score": 90,
            "stub_missing": ["volume"], "stub_entry": 101, "stub_breakout": 100,
        },
        _candidate() | {
            "symbol": "TOP2", "industry": "industry-2", "stub_score": 80,
            "stub_missing": ["trend"], "stub_entry": 105, "stub_breakout": 100,
        },
        _candidate() | {
            "symbol": "OUTSIDE", "industry": "industry-3", "stub_score": 70,
            "stub_missing": ["trend"], "stub_entry": 110, "stub_breakout": 100,
        },
    ]
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: (candidates, []))
    monkeypatch.setattr(
        "app.short_term_decision.calculate_technical_indicators",
        lambda _: {"indicators": {}},
    )

    def fake_decision(row, *args, **kwargs):
        return {
            **row,
            "trade_plan": {
                "reference_entry": row["stub_entry"],
                "breakout_level": row["stub_breakout"],
            },
            "event_risk": {},
            "data_quality_blockers": [],
        }

    monkeypatch.setattr("app.short_term_decision._decision_for_candidate", fake_decision)
    monkeypatch.setattr(
        "app.short_term_decision._research_priority_score",
        lambda decision: (decision["stub_score"], [], [], {}),
    )
    monkeypatch.setattr(
        "app.short_term_decision._execution_status",
        lambda decision: ("waiting_trigger", "waiting"),
    )
    monkeypatch.setattr(
        "app.short_term_decision._operation_gap",
        lambda decision: {
            "missing_count": len(decision["stub_missing"]),
            "missing_checks": [{"key": key} for key in decision["stub_missing"]],
            "breakout_gap_percent": max(
                (decision["stub_breakout"] / decision["stub_entry"] - 1) * 100,
                0,
            ),
            "volume_gap_percent": 5 if "volume" in decision["stub_missing"] else 0,
            "rr_is_provisional": True,
        },
    )

    result = build_short_term_decisions(
        _Database(), {"as_of": "2026-07-31", "market_score": 60, "index_change_20d": 0},
        date(2026, 8, 2), limit=2,
    )

    attention_symbols = [row["symbol"] for row in result["attention_rankings"]]
    closest_symbols = [row["symbol"] for row in result["closest_operation_candidates"]]
    assert attention_symbols == ["TOP1", "TOP2"]
    assert closest_symbols == ["TOP1", "TOP2"]


def test_near_limit_up_is_not_reported_as_operation_ready_or_only_rr_failure(monkeypatch):
    monkeypatch.setattr("app.short_term_decision._evaluated_candidates", lambda *args: ([_candidate()], []))
    monkeypatch.setattr(
        "app.short_term_decision.calculate_technical_indicators",
        lambda _: _indicators(return_1d_percent=9.5),
    )

    result = build_short_term_decisions(
        _Database(), {"as_of": "2026-07-31", "market_score": 60, "index_change_20d": 0},
        date(2026, 8, 2),
    )

    decision = result["decisions"][0]
    assert decision["operation_status"] == "blocked"
    assert result["operation_ready_candidates"] == []
    assert result["closest_operation_candidates"] == []


def test_extreme_pe_cross_check_mismatch_requires_financial_refresh():
    assessment = assess_short_term_fundamentals({
        "close": 28.65,
        "latest_price_date": "2026-08-11",
        "latest_financial_date": "2026-03-31",
        "latest_financial_available_date": "2026-05-15",
        "latest_valuation_date": "20260810",
        "valuation_close": 27.5,
        "ttm_eps": .67,
        "reported_pe_ratio": 11.04,
        "reported_pb_ratio": 1.03,
        "total_assets": 44_846_222_000,
        "total_liabilities": 22_698_723_000,
        "latest_net_income": 501_754_000,
        "latest_operating_income": 651_038_000,
        "operating_income_yoy_percent": 32.188,
        "cash_flow_safety_value": 1_268_695_000,
        "ttm_free_cash_flow": 1_268_695_000,
        "latest_revenue_yoy_percent": 32.52,
    })

    assert assessment["pe_cross_check_difference_percent"] > 200
    assert assessment["passed"] is False
    assert assessment["status"] == "data_pending"
    assert "valuation_earnings_mismatch_requires_refresh" in assessment["blocking_codes"]


def test_zero_ttm_eps_from_rounded_quarters_does_not_fake_data_mismatch():
    assessment = assess_short_term_fundamentals({
        "close": 24.1,
        "latest_price_date": "2026-08-14",
        "latest_financial_date": "2026-06-30",
        "latest_financial_available_date": "2026-08-13",
        "latest_valuation_date": "20260813",
        "valuation_close": 24.1,
        "ttm_eps": 1.1102230246251565e-16,
        "ttm_net_income": 10_406_000,
        "reported_pe_ratio": 200.83,
        "reported_pb_ratio": 1.5,
        "total_assets": 3_000_000_000,
        "total_liabilities": 1_200_000_000,
        "latest_net_income": 72_321_000,
        "latest_operating_income": 80_000_000,
        "operating_income_yoy_percent": 20,
        "cash_flow_safety_value": 10_000_000,
        "ttm_free_cash_flow": 10_000_000,
        "latest_revenue_yoy_percent": 10,
    })

    assert assessment["status"] == "blocked"
    assert assessment["requires_financial_refresh"] is False
    assert assessment["ttm_eps"] is None
    assert assessment["reported_implied_ttm_eps"] == .12
    assert assessment["ttm_eps_reconstruction_status"] == (
        "unreliable_rounded_quarterly_eps_cancellation"
    )
