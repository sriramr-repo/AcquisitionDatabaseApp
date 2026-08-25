import duckdb

from src.gold import GoldBuilder


class IsolatedStorage:
    def __init__(self, connection):
        self.connection = connection

    def get_connection(self):
        return self.connection


def test_gold_builder_builds_isolated_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr("src.gold.settings.GOLD_DIR", tmp_path / "gold")
    connection = duckdb.connect(str(tmp_path / "analytics.duckdb"))
    connection.execute(
        """
        CREATE TABLE silver_firms_fixture AS
        SELECT * FROM (
            VALUES
                (1, 1000000000.0, 2, 0),
                (2, 2000000000.0, 4, 1),
                (3, NULL, 0, 0)
        ) AS firms(crd_number, total_aum, private_fund_count, disciplinary_event_count)
        """
    )

    result = GoldBuilder(IsolatedStorage(connection)).build_gold("fixture")

    assert {"score_aum", "score_growth", "score_risk", "acquisition_score"}.issubset(
        result.columns
    )
    assert len(result) == 3
    assert (tmp_path / "gold" / "fixture" / "gold_firms_fixture.parquet").is_file()
