import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
from src.config import settings
from src.storage import DatasetRegistry

# Use DatasetRegistry for all metadata operations (SQLite = metadata only)
_registry = DatasetRegistry()

def init_metadata():
    """Initialize metadata schema for dataset tracking."""
    _registry.init_schema()

def log_ingestion(data: dict):
    """Register ingestion metadata with registry."""
    _registry.register(data)

def dataset_exists(dataset_version: str) -> bool:
    """Check if dataset already exists with successful status."""
    return _registry.exists(dataset_version)

def list_datasets() -> List[Dict[str, Any]]:
    """List all ingested datasets."""
    return _registry.list()

def get_current_dataset() -> Optional[Dict[str, Any]]:
    """Get currently active dataset."""
    return _registry.get_current()
