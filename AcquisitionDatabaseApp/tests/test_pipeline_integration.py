import pytest
import pandas as pd
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
sys.path.insert(0, 'src')
from pipeline import run_pipeline
from config import settings

def test_pipeline_with_mocks(tmp_path):
    # Create temporary directories
    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    archive_dir = tmp_path / 'archive'
    archive_dir.mkdir()
    log_dir = tmp_path / 'logs'
    log_dir.mkdir()
    db_file = tmp_path / 'test.db'
    
    # Patch settings for test
    with patch.object(settings, 'RAW_DIR', raw_dir), \
         patch.object(settings, 'ARCHIVE_DIR', archive_dir), \
         patch.object(settings, 'LOG_DIR', log_dir), \
         patch.object(settings, 'DB_FILE', db_file), \
         patch('pipeline.get_latest_url') as mock_url, \
         patch('pipeline.download_zip') as mock_download:
        
        mock_url.return_value = "https://www.sec.gov/files/ia07012026.zip"
        
        # Create a function that will create the ZIP file at the expected path
        def fake_download(url, dest_path):
            import zipfile
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dest_path, 'w') as zf:
                zf.writestr("dummy.csv", "col1,col2\nvalue1,value2")
            return "fake_checksum"
        
        mock_download.side_effect = fake_download
        
        # Mock validation and extraction functions
        with patch('pipeline.validate_zip', return_value=True), \
             patch('pipeline.extract_zip', return_value=1), \
             patch('pipeline.validate_extracted', return_value=True), \
             patch('pipeline.validate_csv', return_value=True), \
             patch('pipeline.load_to_dataframes') as mock_load, \
             patch('pipeline.save_to_db') as mock_save:
            
            mock_load.return_value = {"dummy": pd.DataFrame({"col1": ["value1"], "col2": ["value2"]})}
            mock_save.return_value = (["dummy"], 1)
            
            result = run_pipeline(force=False)
            assert result['status'] in ('skipped', 'success')
            
            # Verify metadata was created
            assert db_file.exists()
            conn = sqlite3.connect(db_file)
            cur = conn.execute("SELECT COUNT(*) FROM ingestion_metadata")
            count = cur.fetchone()[0]
            assert count == 1
            conn.close()
