from datetime import date, timedelta

from app.technical_timing import assess_technical_timing


def _rows(count: int = 80, slope: float = 1.0) -> list[dict]:
    return [{"trade_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
             "open": 100 + slope * index - .5, "high": 101 + slope * index,
             "low": 99 + slope * index, "close": 100 + slope * index,
             "volume": 1_000 + index * 3}
            for index in range(count)]


def test_timing_requires_full_trend_warmup():
    report = assess_technical_timing(_rows(59), {})
    assert report["status"] == "insufficient_data"
    assert report["score"] is None


def test_timing_reports_trend_relative_strength_and_extension():
    report = assess_technical_timing(_rows(slope=.1), {"index_change_20d": 1})
    assert report["status"] == "available"
    assert report["signal"] == "favorable"
    assert report["indicators"]["relative_strength_20d_percent"] > 0
    assert "technical_trend_confirmed" in report["reasons"]
    assert report["indicators"]["adx_14"] is not None
    assert report["position_multiplier"] == .5  # one-way synthetic flow makes MFI overbought


def test_timing_marks_weak_trend_as_avoid():
    report = assess_technical_timing(_rows(slope=-1), {"index_change_20d": 0})
    assert report["signal"] == "avoid"
    assert "technical_trend_not_confirmed" in report["risks"]
