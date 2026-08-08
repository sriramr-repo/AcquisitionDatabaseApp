import pytest
from pathlib import Path
from archive import archive_dataset
from config import settings
from unittest.mock import patch

def test_archive_logic(tmp_path):
    raw_dir = tmp_path / 'raw'
    archive_dir = tmp_path / 'archive'
    raw_dir.mkdir()
    archive_dir.mkdir()
    
    # Create fake dataset
    ds_name = 'test_ds'
    ds_path = raw_dir / ds_name
    ds_path.mkdir()
    (ds_path / 'data.csv').write_text('test')
    zip_path = raw_dir / f'{ds_name}.zip'
    zip_path.write_text('fake zip content')
    
    with patch.object(settings, 'RAW_DIR', raw_dir), \
         patch.object(settings, 'ARCHIVE_DIR', archive_dir):
        archive_dataset(ds_name)
        
        # Verify moved
        assert not ds_path.exists()
        assert not zip_path.exists()
        assert (archive_dir / ds_name).exists()
        assert (archive_dir / f'{ds_name}.zip').exists()
