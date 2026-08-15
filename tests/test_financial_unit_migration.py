from pathlib import Path

from app.database import Database


def test_initialize_normalizes_only_legacy_official_thousand_unit_rows(tmp_path: Path):
    database = Database(tmp_path / "stocks.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany(
            """INSERT INTO financial_snapshots(
                   symbol,market,fiscal_year,fiscal_quarter,report_type,revenue,
                   gross_profit,operating_income,net_income,eps,total_assets,
                   total_liabilities,equity,book_value_per_share,statement_date,source)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                ("1516", "TWSE", 2026, 1, "ci", 26_221, 1_603, -2_315,
                 -2_088, -.05, 207_462, 2_870, 204_592, 5.11,
                 "2026-03-31", "TWSE official OpenAPI"),
                ("8024", "TPEx", 2026, 1, "ci", 34_683, 10_297, -26_826,
                 -24_790, -.55, 440_894, 39_776, 401_118, 8.88,
                 "2026-03-31", "TPEx official OpenAPI"),
                ("4561", "TPEx", 2026, 2, "ci", 563_524_000, 144_447_000,
                 73_318_000, 63_791_000, 1.09, 2_346_267_000, 931_813_000,
                 1_414_454_000, 24.17, "2026-06-30", "TPEx official OpenAPI"),
                ("9001", "TWSE", 2026, 2, "ci", 123_000_000, 45_000_000,
                 12_000_000, 8_000_000, 1.2, 700_000_000, 200_000_000,
                 500_000_000, 20.0, "2026-06-30",
                 "TWSE official OpenAPI / amount-normalized-x1000"),
                ("9002", "TPEx", 2026, 2, "ci", 321_000_000, 80_000_000,
                 20_000_000, 15_000_000, 2.3, 900_000_000, 300_000_000,
                 600_000_000, 30.0, "2026-06-30", "TPEx official OpenAPI"),
            ],
        )
        connection.executemany(
            """INSERT INTO monthly_revenues(
                   symbol,market,revenue_month,revenue,cumulative_revenue)
               VALUES(?,?,?,?,?)""",
            [
                ("1516", "TWSE", "2026-03", 12_000, 26_221),
                ("4561", "TPEx", "2026-06", 109_091, 563_524),
            ],
        )
        connection.execute(
            """UPDATE financial_snapshots SET fetched_at='2026-07-31 07:10:37'
               WHERE symbol='8024'"""
        )
        connection.execute(
            """UPDATE financial_snapshots SET fetched_at='2026-08-04 09:00:00'
               WHERE symbol='9001'"""
        )
        connection.execute(
            """UPDATE financial_snapshots SET fetched_at='2026-08-12 09:00:00'
               WHERE symbol='9002'"""
        )

    database.initialize()
    with database.connect() as connection:
        legacy = dict(connection.execute(
            "SELECT * FROM financial_snapshots WHERE symbol='1516'"
        ).fetchone())
        current = dict(connection.execute(
            "SELECT * FROM financial_snapshots WHERE symbol='4561'"
        ).fetchone())
        legacy_without_quarter_revenue = dict(connection.execute(
            "SELECT * FROM financial_snapshots WHERE symbol='8024'"
        ).fetchone())
        explicitly_normalized = dict(connection.execute(
            "SELECT * FROM financial_snapshots WHERE symbol='9001'"
        ).fetchone())
        post_rollout = dict(connection.execute(
            "SELECT * FROM financial_snapshots WHERE symbol='9002'"
        ).fetchone())

    assert legacy["revenue"] == 26_221_000
    assert legacy["net_income"] == -2_088_000
    assert legacy["total_assets"] == 207_462_000
    assert legacy["eps"] == -.05
    assert legacy["book_value_per_share"] == 5.11
    assert legacy["monetary_unit"] == "TWD"
    assert current["revenue"] == 563_524_000
    assert current["total_assets"] == 2_346_267_000
    assert current["monetary_unit"] == "TWD"
    assert legacy_without_quarter_revenue["revenue"] == 34_683_000
    assert legacy_without_quarter_revenue["net_income"] == -24_790_000
    assert legacy_without_quarter_revenue["monetary_unit"] == "TWD"
    assert explicitly_normalized["revenue"] == 123_000_000
    assert explicitly_normalized["monetary_unit"] == "TWD"
    assert post_rollout["revenue"] == 321_000_000
    assert post_rollout["monetary_unit"] == "TWD"
