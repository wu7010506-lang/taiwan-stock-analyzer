from datetime import date, timedelta

from app.short_analysis import _plain_short_term_conclusion, _short_term_report


def _plan(**overrides):
    plan = {
        "status": "條件通過，開盤前仍須重算",
        "reference_entry": 100, "maximum_entry_price": 101,
        "stop": 96, "planned_target": 110,
        "cost_adjusted_risk_reward": 2.1, "required_rr": 2,
        "soft_risks": [],
        "trigger_checks": {
            "breakout": {"passed": True, "actual": 100, "required_above": 98},
            "trend": {"passed": True},
            "volume": {"passed": True, "actual_ratio": 1.4, "required_ratio": 1.3},
            "atr_risk": {"passed": True},
            "risk_reward": {"passed": True, "actual": 2.1, "required": 2},
            "market_access": {"passed": True},
        },
    }
    plan.update(overrides)
    return plan


def test_plain_conclusion_explains_exact_missing_conditions():
    plan = _plan()
    plan["trigger_checks"] = {
        **plan["trigger_checks"],
        "breakout": {"passed": False, "actual": 95, "required_above": 100},
        "volume": {"passed": False, "actual_ratio": 1.0, "required_ratio": 1.3},
        "risk_reward": {"passed": False, "actual": .5, "required": 2, "provisional": True},
    }

    result = _plain_short_term_conclusion(plan, "2026-08-10")

    assert result["answer_code"] == "wait"
    assert result["headline"] == "現在先不要買，等待條件完成"
    assert len(result["missing_conditions"]) == 2
    assert "95.00" in result["missing_conditions"][0]
    assert "1.00 倍" in result["missing_conditions"][1]
    assert "RR" not in result["summary"]


def test_plain_conclusion_rejects_independent_target_with_insufficient_rr():
    plan = _plan(cost_adjusted_risk_reward=1.2)
    plan["trigger_checks"] = {
        **plan["trigger_checks"],
        "risk_reward": {"passed": False, "actual": 1.2, "required": 2, "provisional": False},
    }

    result = _plain_short_term_conclusion(plan, "2026-08-10")

    assert result["answer_code"] == "avoid"
    assert result["headline"] == "現在不建議買，獲利空間不夠"
    assert "1：1.20" in result["summary"]


def test_plain_conclusion_only_exposes_prices_for_completed_setup():
    result = _plain_short_term_conclusion(_plan(), "2026-08-10")

    assert result["answer_code"] == "conditional"
    assert result["reference_prices"]["maximum_entry"] == 101
    assert result["reference_prices"]["stop"] == 96
    assert result["reference_prices"]["target"] == 110


def test_plain_conclusion_blocks_technical_setup_when_fundamentals_fail():
    result = _plain_short_term_conclusion(
        _plan(),
        "2026-08-11",
        fundamental_assessment={
            "passed": False,
            "blocking_reasons": [
                "本益比 58.3 倍偏高，且本業獲利年減 44.5%",
                "本業獲利只相當於稅後淨利的 38.8%",
            ],
        },
    )

    assert result["answer_code"] == "avoid"
    assert result["headline"] == "不建議買進：基本面安全門檻未通過"
    assert "58.3 倍" in result["summary"]
    assert result["reference_prices"] is None


def test_presented_report_keeps_plain_conclusion_machine_code_stable():
    rows = []
    start = date(2026, 5, 1)
    for index in range(60):
        close = 100 + index * .1
        rows.append({
            "trade_date": (start + timedelta(days=index)).isoformat(),
            "open": close - .2, "high": close + .5, "low": close - .5,
            "close": close, "volume": 1000,
        })
    values = {
        "atr_14": 2, "breakout_level_20d": 110,
        "trend_confirmation": False, "volume_ratio_20": 1,
        "rsi_14": 50, "mfi_14": 50, "natr_14": 2,
    }

    report = _short_term_report(rows, values, rows[-1]["trade_date"], "range")

    assert report["plain_conclusion"]["answer_code"] == "wait"


def test_presented_report_keeps_technical_trigger_machine_code_stable():
    rows = []
    start = date(2026, 5, 1)
    for index in range(60):
        close = 100 + index * .1
        rows.append({
            "trade_date": (start + timedelta(days=index)).isoformat(),
            "open": close - .2, "high": close + .5, "low": close - .5,
            "close": close, "volume": 1000,
        })
    values = {
        "atr_14": 2, "breakout_level_20d": 110,
        "trend_confirmation": False, "volume_ratio_20": 1,
        "rsi_14": 50, "mfi_14": 50, "natr_14": 2,
    }
    fundamental = {"passed": False, "blocking_reasons": ["基本面未通過"]}

    report = _short_term_report(
        rows, values, rows[-1]["trade_date"], "range", fundamental
    )

    assert report["plain_conclusion"]["technical_trigger_status"] == "not_confirmed"
    assert report["plain_conclusion"]["investment_status"] == "do_not_buy"
