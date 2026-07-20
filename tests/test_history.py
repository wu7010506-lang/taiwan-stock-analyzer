from datetime import date

import httpx

from app.providers import TpexProvider, TwseProvider
from app.service import _months_between


def test_months_between_crosses_year():
    assert _months_between(date(2025, 12, 20), date(2026, 2, 1)) == [
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]


def test_twse_history_parser():
    payload = {
        "stat": "OK",
        "data": [["115/06/01", "1,000", "2,000,000", "20", "22", "19", "21", "+1", "50", ""]],
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    row = TwseProvider(client).fetch_history_month("2330", date(2026, 6, 1))[0]
    assert row.trade_date == date(2026, 6, 1)
    assert row.volume == 1000
    assert row.close == 21


def test_tpex_history_parser_converts_thousands():
    payload = {"tables": [{"data": [["115/06/01", "1,557", "377,879", "242.5", "247", "240", "244", "2.5", "2,234"]]}]}
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    row = TpexProvider(client).fetch_history_month("3455", date(2026, 6, 1))[0]
    assert row.volume == 1_557_000
    assert row.turnover == 377_879_000
