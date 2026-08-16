import pytest
import sys
from pathlib import Path
import shutil
import sqlite3

# Add src to sys.path for imports during testing
sys.path.append(str(Path(__file__).parent.parent))

from src.profiling.profiler import ProfileService, DatasetProfiler
from src.storage import StorageManager, PathResolver, DatasetRegistry
from src.config import settings

@pytest.fixture
def setup_test_environment(tmp_path):
    """Sets up a temporary environment for profiling tests."""
    test_base_dir = tmp_path / "test_data"
    test_base_dir.mkdir(parents=True, exist_ok=True)
    
    # Override settings for temporary paths
    with pytest.MonkeyPatch.context() as m:
        m.setattr(settings, 'BASE_DIR', test_base_dir)
        m.setattr(settings, 'BRONZE_DIR', test_base_dir / "bronze")
        m.setattr(settings, 'SILVER_DIR', test_base_dir / "silver")
        m.setattr(settings, 'GOLD_DIR', test_base_dir / "gold")
        m.setattr(settings, 'ARCHIVE_DIR', test_base_dir / "archive")
        m.setattr(settings, 'EXPORTS_DIR', test_base_dir / "exports")
        m.setattr(settings, 'LOG_DIR', test_base_dir / "logs")
        m.setattr(settings, 'DB_FILE', test_base_dir / "metadata.db")
        m.setattr(settings, 'DUCKDB_FILE', test_base_dir / "analytics.duckdb")

        # Ensure directories exist
        for path in [
            settings.BRONZE_DIR, settings.SILVER_DIR, settings.GOLD_DIR,
            settings.ARCHIVE_DIR, settings.EXPORTS_DIR, settings.LOG_DIR
        ]:
            path.mkdir(parents=True, exist_ok=True)
        
        # Initialize the test registry and storage manager
        registry = DatasetRegistry(db_path=settings.DB_FILE)
        registry.init_schema()
        storage_manager = StorageManager()

        yield storage_manager, registry, test_base_dir

def test_profiling_service_instantiation_and_basic_profile(setup_test_environment):
    storage_manager, registry, test_base_dir = setup_test_environment

    dataset_version = "ia07012026"
    table_name = "bronze_raw_testentity_ia07012026"

    # Create a dummy table in DuckDB
    conn = storage_manager.get_connection()
    conn.execute(f"CREATE TABLE {table_name} (id INTEGER, name VARCHAR);")
    conn.execute(f"INSERT INTO {table_name} VALUES (1, 'Test A'), (2, 'Test B');")
    conn.close()

    # Register the dataset
    registry.register({
        'dataset_version': dataset_version,
        'dataset_name': 'test_dataset',
        'source_url': 'http://example.com',
        'download_timestamp': '2023-01-01',
        'file_name': 'test.zip',
        'file_size': 100,
        'sha256_checksum': 'abc',
        'status': 'success',
        'notes': 'test dataset'
    })

    service = ProfileService(storage_manager=storage_manager)
    assert service is not None

    # Run profile for the dummy table
    profile_results = service.profile_table(dataset_version, table_name)
    
    assert 'dataset_version' in profile_results
    assert 'table_name' in profile_results
    assert 'profiles' in profile_results
    assert 'schema' in profile_results['profiles']
    assert 'quality' in profile_results['profiles']
    
    # Verify metadata registration for artifacts
    with registry._connect() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE dataset_version = ? AND artifact_type LIKE 'profiling/%'",
            (dataset_version,)
        )
        assert cursor.fetchone()[0] > 0