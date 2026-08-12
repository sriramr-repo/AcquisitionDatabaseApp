import sqlite3
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
import duckdb

from src.config import settings


class PathResolver:
    """Centralized path resolution for medallion architecture."""

    @staticmethod
    def bronze_raw(dataset_name: str) -> Path:
        """Path to extracted CSV files in bronze layer."""
        return settings.BRONZE_DIR / "raw" / dataset_name

    @staticmethod
    def bronze_raw_zip(dataset_name: str) -> Path:
        """Path to ZIP file in bronze layer."""
        return settings.BRONZE_DIR / "raw" / f"{dataset_name}.zip"

    @staticmethod
    def silver_table(entity: str, dataset_version: str) -> str:
        """Silver table name convention."""
        return f"silver_{entity}_{dataset_version.replace('-', '')}"

    @staticmethod
    def artifact(dataset_name: str, artifact_type: str, filename: str) -> Path:
        """Path for profiling, dictionary, validation reports."""
        return settings.BASE_DIR / artifact_type / dataset_name / filename

    @staticmethod
    def archive_extracted(dataset_name: str) -> Path:
        """Path to archived extracted directory."""
        return settings.ARCHIVE_DIR / dataset_name

    @staticmethod
    def archive_zip(dataset_name: str) -> Path:
        """Path to archived ZIP file."""
        return settings.ARCHIVE_DIR / f"{dataset_name}.zip"


class DatasetRegistry:
    """Dataset version tracking and metadata operations."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or settings.DB_FILE

    def init_schema(self):
        """Create tables for dataset tracking."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_version TEXT PRIMARY KEY,
                    dataset_name TEXT,
                    source_url TEXT,
                    download_timestamp DATETIME,
                    file_name TEXT,
                    file_size INTEGER,
                    sha256_checksum TEXT,
                    status TEXT,
                    notes TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY,
                    dataset_version TEXT,
                    artifact_type TEXT,
                    file_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def register(self, meta: dict):
        """Register new dataset ingestion."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO datasets (
                    dataset_version, dataset_name, source_url, download_timestamp,
                    file_name, file_size, sha256_checksum, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                meta.get('dataset_version'),
                meta.get('dataset_name'),
                meta.get('source_url'),
                meta.get('download_timestamp'),
                meta.get('file_name'),
                meta.get('file_size'),
                meta.get('sha256_checksum'),
                meta.get('status'),
                meta.get('notes')
            ))

    def exists(self, dataset_version: str) -> bool:
        """Check if dataset exists and has successful status."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT 1 FROM datasets WHERE dataset_version = ? AND status = 'success'",
                (dataset_version,)
            )
            return cur.fetchone() is not None

    def list(self) -> List[Dict[str, Any]]:
        """List all datasets with metadata."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM datasets ORDER BY download_timestamp DESC"
            )]

    def get_current(self) -> Optional[Dict[str, Any]]:
        """Get currently active dataset."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM datasets WHERE status = 'success' ORDER BY download_timestamp DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    @contextmanager
    def _connect(self):
        """Context manager for SQLite connection."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()


class StorageManager:
    """Unified interface for storage operations across medallion layers."""

    def __init__(self):
        self.registry = DatasetRegistry()
        self.registry.init_schema()

    def get_connection(self):
        """Get DuckDB connection for analytical workloads."""
        return duckdb.connect(str(settings.DUCKDB_FILE))

    def save_artifact(self, dataset_version: str, artifact_type: str, filename: str, content: str):
        """Persist artifact to disk and metadata DB."""
        path = PathResolver.artifact(dataset_version, artifact_type, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        with self.registry._connect() as conn:
            conn.execute(
                "INSERT INTO artifacts (dataset_version, artifact_type, file_path) VALUES (?, ?, ?)",
                (dataset_version, artifact_type, str(path))
            )
            conn.commit()

    def archive_dataset(self, dataset_name: str):
        """Archive dataset to archive layer using resolver paths."""
        bronze = PathResolver.bronze_raw(dataset_name)
        zip_path = PathResolver.bronze_raw_zip(dataset_name)

        if bronze.exists():
            dest = PathResolver.archive_extracted(dataset_name)
            if dest.exists():
                shutil.rmtree(str(dest))
            shutil.move(str(bronze), str(dest))

        if zip_path.exists():
            dest = PathResolver.archive_zip(dataset_name)
            if dest.exists():
                dest.unlink()
            shutil.move(str(zip_path), str(dest))


# Singleton for backward compatibility
storage = StorageManager()