import sqlite3
import sys
from datetime import datetime
from typing import Optional, List, Dict, Any
from src.config import settings
from src.storage import DatasetRegistry

# Use DatasetRegistry for all metadata operations (SQLite = metadata only)
_registry = DatasetRegistry()


def _active_registry() -> DatasetRegistry:
    """Keep the compatibility singleton aligned with the active environment."""
    global _registry
    active_settings = settings if __name__.startswith("src.") else getattr(sys.modules.get("config"), "settings", settings)
    if _registry.db_path.resolve() != active_settings.DB_FILE.resolve():
        _registry = DatasetRegistry(active_settings.DB_FILE)
    return _registry

def init_metadata():
    """Initialize metadata schema for dataset tracking."""
    _active_registry().init_schema()

def log_ingestion(data: dict):
    """Register ingestion metadata with registry."""
    _active_registry().register(data)

def dataset_exists(dataset_version: str) -> bool:
    """Check if dataset already exists with successful status."""
    return _active_registry().exists(dataset_version)

def list_datasets() -> List[Dict[str, Any]]:
    """List all ingested datasets."""
    return _active_registry().list()

def get_current_dataset() -> Optional[Dict[str, Any]]:
    """Get currently active dataset."""
    return _active_registry().get_current()
