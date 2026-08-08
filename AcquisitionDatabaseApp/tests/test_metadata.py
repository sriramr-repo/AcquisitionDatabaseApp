import pytest
import sys
sys.path.append('src')
from metadata import init_metadata, dataset_exists
from config import settings
import sqlite3
from pathlib import Path

def test_init_metadata(tmp_path):
    # Use a temporary database for testing
    test_db = tmp_path / 'test.db'
    # Patch the DB_FILE in settings
    with pytest.MonkeyPatch.context() as m:
        m.setattr(settings, 'DB_FILE', test_db)
        init_metadata()
        assert test_db.exists()
        # Check the table exists
        conn = sqlite3.connect(test_db)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        assert 'ingestion_metadata' in tables
        conn.close()
