import logging
import sqlite3
import sys
import types
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.config import settings


def test_pipeline_with_mocks(tmp_path):
    test_base_dir = tmp_path / "data"
    paths = {
        "BASE_DIR": test_base_dir,
        "BRONZE_DIR": test_base_dir / "bronze",
        "SILVER_DIR": test_base_dir / "silver",
        "GOLD_DIR": test_base_dir / "gold",
        "ARCHIVE_DIR": test_base_dir / "archive",
        "EXPORTS_DIR": test_base_dir / "exports",
        "LOG_DIR": test_base_dir / "logs",
        "RAW_DIR": test_base_dir / "bronze" / "raw",
        "DB_FILE": test_base_dir / "metadata.db",
        "DB_PATH": f"sqlite:///{test_base_dir / 'metadata.db'}",
        "DUCKDB_FILE": test_base_dir / "analytics.duckdb",
    }
    for name, value in paths.items():
        if name.endswith("_DIR") or name == "RAW_DIR":
            value.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        for name, value in paths.items():
            stack.enter_context(patch.object(settings, name, value))

        import src.archive as archive_module
        import src.metadata as metadata_module
        import src.pipeline as pipeline_module
        import src.storage as storage_module
        from src.storage import DatasetRegistry, PathResolver, StorageManager

        # Rebind import-time singletons to the temporary configuration.
        temporary_storage = StorageManager()
        storage_module.storage = temporary_storage
        archive_module.storage = temporary_storage
        metadata_module._registry = DatasetRegistry(paths["DB_FILE"])
        pipeline_module.storage = temporary_storage

        # Keep this integration test focused on pipeline isolation. The real
        # GoldBuilder module currently has an unrelated syntax defect, so use
        # a test-only stub rather than changing production scoring code.
        fake_gold_module = types.ModuleType("src.gold")

        class FakeGoldBuilder:
            def __init__(self, storage):
                self.storage = storage

            def build_gold(self, version):
                return pd.DataFrame()

        fake_gold_module.GoldBuilder = FakeGoldBuilder
        stack.enter_context(patch.dict(sys.modules, {"src.gold": fake_gold_module}))

        isolated_logger = logging.getLogger(f"test.pipeline.{id(tmp_path)}")
        isolated_logger.handlers.clear()
        isolated_logger.propagate = False
        isolated_logger.addHandler(logging.NullHandler())

        stack.enter_context(patch.object(pipeline_module, "logger", isolated_logger))
        mock_url = stack.enter_context(patch.object(pipeline_module, "get_latest_url"))
        mock_download = stack.enter_context(patch.object(pipeline_module, "download_zip"))
        stack.enter_context(patch.object(pipeline_module, "validate_zip", return_value=True))
        stack.enter_context(patch.object(pipeline_module, "extract_zip", return_value=1))
        stack.enter_context(patch.object(pipeline_module, "validate_extracted", return_value=True))
        stack.enter_context(patch.object(pipeline_module, "validate_csv", return_value=True))
        mock_load = stack.enter_context(patch.object(pipeline_module, "load_to_dataframes"))
        mock_save = stack.enter_context(patch.object(pipeline_module, "save_to_db"))

        mock_url.return_value = "https://www.sec.gov/files/ia07012026.zip"

        def fake_download(url, dest_path):
            import zipfile

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dest_path, "w") as zip_file:
                zip_file.writestr("dummy.csv", "col1,col2\nvalue1,value2")
            return "fake_checksum"

        mock_download.side_effect = fake_download
        mock_load.return_value = {"dummy": pd.DataFrame({"col1": ["value1"], "col2": ["value2"]})}
        mock_save.return_value = (["dummy"], 1)

        resolved_bronze_zip = PathResolver.bronze_raw_zip("ia07012026").resolve()
        assert resolved_bronze_zip.is_relative_to(test_base_dir.resolve())
        assert not resolved_bronze_zip.is_relative_to(Path("data").resolve())

        result = pipeline_module.run_pipeline(force=False)
        assert result["status"] in ("skipped", "success")
        assert resolved_bronze_zip.exists()
        assert resolved_bronze_zip.parent.is_relative_to(test_base_dir.resolve())

        db_file = paths["DB_FILE"]
        assert db_file.exists()
        with sqlite3.connect(db_file) as connection:
            count = connection.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        assert count == 1
