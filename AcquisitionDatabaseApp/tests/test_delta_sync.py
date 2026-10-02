import duckdb
import pytest

from src.delta_sync import parse_gold_table, sync_gold_to_delta

deltalake = pytest.importorskip("deltalake")


def test_parse_gold_table_names():
    assert parse_gold_table("gold_firms_ia07012026") == ("gold_firms", "ia07012026")
    assert parse_gold_table("gold_scm_acquisition_v1_ia08032026_0") == (
        "gold_scm_acquisition_v1", "ia08032026_0",
    )
    assert parse_gold_table("silver_firms_ia07012026") is None


def test_sync_writes_partitioned_delta_and_is_idempotent(tmp_path):
    db = tmp_path / "analytics.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE gold_firms_ia07012026 AS SELECT * FROM (VALUES (1, 0.5), (2, 0.9)) t(crd, score)")
    conn.execute("CREATE TABLE gold_firms_ia08032026_0 AS SELECT * FROM (VALUES (1, 0.6, 'stale')) t(crd, score, dataset_version)")
    conn.close()
    target = tmp_path / "delta"

    for _ in range(2):
        manifest = sync_gold_to_delta(target=target, duckdb_file=db)

    table = deltalake.DeltaTable(str(target / "gold_firms")).to_pyarrow_table()
    assert table.num_rows == 3
    assert sorted(set(table.column("dataset_version").to_pylist())) == ["ia07012026", "ia08032026_0"]
    assert "USING DELTA LOCATION" in manifest["unity_catalog_ddl"][0]
    assert (target / "_sync_manifest.json").is_file()
