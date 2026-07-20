from app.database import Database
from app.domain import Instrument
from app.recommendations import _percentile, recommend_stocks


def test_percentile_supports_inverse_ranking():
    assert _percentile(30, [10, 20, 30]) == 1
    assert _percentile(10, [10, 20, 30], inverse=True) == 1


def test_recommendations_require_sufficient_data(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    database.upsert_instruments([Instrument("2330", "台積電", "TWSE", "半導體業")])
    assert recommend_stocks(database) == []
    assert recommend_stocks(database, profile="value") == []
