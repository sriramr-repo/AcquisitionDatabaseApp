import pytest
import sys
import sqlite3
from pathlib import Path
sys.path.append('src')
from storage import DatasetRegistry
from config import settings

def test_register_persists_to_disk(tmp_path):
    """Test that DatasetRegistry.register() persists data to disk."""
    # 1. Create isolated temporary SQLite database
    test_db = tmp_path / 'test_metadata.db'
    
    # 2. Initialize schema and register a dataset
    with pytest.MonkeyPatch.context() as m:
        m.setattr(settings, 'DB_FILE', test_db)
        registry = DatasetRegistry(test_db)
        registry.init_schema()
        
        # 3. Register test dataset
        registry.register({
            'dataset_version': 'test_dataset',
            'dataset_name': 'test_dataset',
            'source_url': 'https://example.com',
            'download_timestamp': '2026-01-07T00:00:00',
            'file_name': 'test.zip',
            'file_size': 1000,
            'sha256_checksum': 'abc123',
            'status': 'success',
            'notes': ''
        })
    
    # 4. Close and reopen database
    conn = sqlite3.connect(str(test_db))
    cur = conn.execute(
        "SELECT dataset_version, status FROM datasets WHERE dataset_version = ?",
        ('test_dataset',)
    )
    row = cur.fetchone()
    conn.close()
    
    # 5. Verify persistence
    assert row is not None, "Record not found after re-opening database"
    assert row[0] == 'test_dataset', f"Expected 'test_dataset', got '{row[0]}'"
    assert row[1] == 'success', f"Expected 'success', got '{row[1]}'"
    
    # 6. Verify no duplicates
    conn = sqlite3.connect(str(test_db))
    cur = conn.execute("SELECT COUNT(*) FROM datasets WHERE dataset_version = ?", ('test_dataset',))
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1, f"Expected 1 record, found {count}"