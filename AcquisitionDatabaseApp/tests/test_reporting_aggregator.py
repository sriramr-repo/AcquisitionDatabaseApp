import pytest
import sys
import sqlite3
import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List

sys.path.append('src')

from src.storage import DatasetRegistry
from src.config import settings
from src.reports.aggregator import (
    get_dataset_summary,
    get_daily_summary,
    get_monthly_summary,
    get_historical_summary,
    _load_artifacts_for_dataset,
    _extract_quality_metrics,
    _extract_schema_diff_metrics,
    _extract_change_detection_metrics,
    get_all_dataset_summaries
)
from src.reports.models import DatasetSummary, MonthlySummary, HistoricalSummary


@pytest.fixture
def temp_db_path(tmp_path) -> Path:
    """Fixture for a temporary SQLite database path."""
    return tmp_path / 'test_metadata.db'

@pytest.fixture
def setup_registry(temp_db_path) -> DatasetRegistry:
    """Fixture to set up a DatasetRegistry with a temporary database."""
    with pytest.MonkeyPatch.context() as m:
        m.setattr(settings, 'DB_FILE', temp_db_path)
        registry = DatasetRegistry(temp_db_path)
        registry.init_schema()
        return registry

@pytest.fixture
def mock_artifacts_dir(tmp_path) -> Path:
    """Fixture for a temporary artifacts directory."""
    original_base_dir = settings.BASE_DIR
    mock_base_dir = tmp_path / 'data'
    mock_base_dir.mkdir()
    with pytest.MonkeyPatch.context() as m:
        m.setattr(settings, 'BASE_DIR', mock_base_dir)
        yield mock_base_dir
    m.setattr(settings, 'BASE_DIR', original_base_dir) # Restore original


def _add_dataset(registry: DatasetRegistry, **kwargs):
    """Helper to add a dataset to the registry."""
    default_meta = {
        'dataset_version': f'ia{datetime.utcnow().strftime("%Y%m%d%H%M%S")}',
        'dataset_name': 'test_dataset',
        'source_url': 'https://example.com/test.zip',
        'download_timestamp': datetime.utcnow().isoformat(),
        'file_name': 'test.zip',
        'file_size': 1024,
        'sha256_checksum': 'abc',
        'status': 'success',
        'notes': ''
    }
    default_meta.update(kwargs)
    registry.register(default_meta)

def _create_artifact_file(
    mock_base_dir: Path,
    dataset_version: str,
    artifact_type: str,
    filename: str,
    content: Dict[str, Any]
):
    """Helper to create a mock artifact file."""
    path = mock_base_dir / artifact_type / dataset_version / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(content, f)

# --- Test get_dataset_summary ---

def test_get_dataset_summary_not_found(setup_registry):
    summary = get_dataset_summary('non_existent_dataset', setup_registry.db_path)
    assert summary is None

def test_get_dataset_summary_success(setup_registry, mock_artifacts_dir):
    version = 'ia20230101'
    _add_dataset(setup_registry, dataset_version=version, status='success', file_size=2048, notes='Test notes')
    
    # Add mock artifacts
    _create_artifact_file(
        mock_artifacts_dir, version, 'quality', 'report.json',
        {'summary': {'quality_score': 0.95, 'passed': 10, 'failed': 1}}
    )
    _create_artifact_file(
        mock_artifacts_dir, version, 'schema_diff', 'diff.json',
        {'missing': ['col_a'], 'extra': []}
    )
    _create_artifact_file(
        mock_artifacts_dir, version, 'change_detection', 'changes.json',
        {'summary': {'added_count': 5, 'modified_count': 2}}
    )

    summary = get_dataset_summary(version, setup_registry.db_path)
    assert isinstance(summary, DatasetSummary)
    assert summary.dataset_version == version
    assert summary.status == 'success'
    assert summary.file_size == 2048
    assert summary.quality_score == 0.95
    assert summary.quality_checks_passed == 10
    assert summary.quality_checks_failed == 1
    expected_source_file_sd = str(mock_artifacts_dir / 'schema_diff' / version / 'diff.json')
    assert summary.schema_changes == {'missing_columns': 1, 'extra_columns': 0, 'details': {'missing': ['col_a'], 'extra': [], '_source_file': expected_source_file_sd, '_artifact_type': 'schema_diff'}}
    assert summary.data_changes == {'added_count': 5, 'modified_count': 2}
    assert any(a['type'] == 'quality' for a in summary.artifacts)
    assert summary.notes == 'Test notes'

def test_get_dataset_summary_failed(setup_registry):
    version = 'ia20230102'
    _add_dataset(setup_registry, dataset_version=version, status='failed', notes='Validation failed')
    summary = get_dataset_summary(version, setup_registry.db_path)
    assert summary.status == 'failed'
    assert summary.notes == 'Validation failed'
    assert summary.quality_score is None # No artifacts
    assert not summary.artifacts

def test_get_all_dataset_summaries_empty(setup_registry):
    summaries = get_all_dataset_summaries(setup_registry.db_path)
    assert len(summaries) == 0

def test_get_all_dataset_summaries_multiple(setup_registry):
    _add_dataset(setup_registry, dataset_version='v1', status='success')
    _add_dataset(setup_registry, dataset_version='v2', status='failed')
    summaries = get_all_dataset_summaries(setup_registry.db_path)
    assert len(summaries) == 2
    assert sorted([s.dataset_version for s in summaries]) == ['v1', 'v2']

# --- Test artifact extraction helpers ---

def test_load_artifacts_for_dataset_empty(mock_artifacts_dir):
    artifacts = _load_artifacts_for_dataset('non_existent_version')
    assert artifacts == {}

def test_extract_quality_metrics(mock_artifacts_dir):
    version = 'v_quality'
    _create_artifact_file(mock_artifacts_dir, version, 'quality', 'report1.json',
                          {'summary': {'quality_score': 0.8, 'passed': 8, 'failed': 2}})
    score, passed, failed = _extract_quality_metrics(version)
    assert score == 0.8
    assert passed == 8
    assert failed == 2

    # Test with profiling artifact format
    _create_artifact_file(mock_artifacts_dir, version, 'profiling', 'profile.json',
                          {'quality': {'quality_score': 0.7, 'checks_passed': 7, 'checks_failed': 3}})
    score, passed, failed = _extract_quality_metrics(version) # Should pick up the first one found
    assert score == 0.8 # Still the first quality report
    
    # Test only profiling artifact
    shutil.rmtree(mock_artifacts_dir / 'quality' / version)
    score, passed, failed = _extract_quality_metrics(version)
    assert score == 0.7
    assert passed == 7
    assert failed == 3

def test_extract_schema_diff_metrics(mock_artifacts_dir):
    version = 'v_schema'
    filename = 'diff.json'
    _create_artifact_file(mock_artifacts_dir, version, 'schema_diff', filename,
                          {'missing': ['col_a'], 'extra': ['col_b']})
    metrics = _extract_schema_diff_metrics(version)
    
    # Construct the expected path explicitly for assertion
    expected_source_file = str(mock_artifacts_dir / 'schema_diff' / version / filename)
    
    assert metrics == {
        'missing_columns': 1,
        'extra_columns': 1,
        'details': {'missing': ['col_a'], 'extra': ['col_b'], '_source_file': expected_source_file, '_artifact_type': 'schema_diff'}
    }

def test_extract_change_detection_metrics(mock_artifacts_dir):
    version = 'v_change'
    _create_artifact_file(mock_artifacts_dir, version, 'change_detection', 'report.json',
                          {'summary': {'added_count': 10, 'modified_count': 5}})
    metrics = _extract_change_detection_metrics(version)
    assert metrics == {'added_count': 10, 'modified_count': 5}

# --- Test daily, monthly, historical summaries ---

def test_get_daily_summary(setup_registry, mock_artifacts_dir):
    today = datetime.utcnow().strftime('%Y-%m-%d')
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')
    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')

    _add_dataset(setup_registry, dataset_version='v_today_1', status='success', download_timestamp=f'{today}T10:00:00')
    _add_dataset(setup_registry, dataset_version='v_today_2', status='failed', download_timestamp=f'{today}T11:00:00')
    _add_dataset(setup_registry, dataset_version='v_yesterday', status='success', download_timestamp=f'{yesterday}T12:00:00')

    summary = get_daily_summary(today, setup_registry.db_path)
    assert isinstance(summary, MonthlySummary)
    assert summary.total_ingestion_attempts == 2
    assert summary.successful_ingestions == 1
    assert summary.failed_ingestions == 1
    assert sorted(summary.datasets_processed) == ['v_today_1', 'v_today_2']

    summary_no_data = get_daily_summary(tomorrow, setup_registry.db_path)
    assert summary_no_data is None

def test_get_monthly_summary(setup_registry, mock_artifacts_dir):
    year, month = datetime.utcnow().year, datetime.utcnow().month
    
    # Datasets for current month
    _add_dataset(setup_registry, dataset_version='m_v1', status='success', download_timestamp=datetime(year, month, 5).isoformat())
    _add_dataset(setup_registry, dataset_version='m_v2', status='failed', download_timestamp=datetime(year, month, 15).isoformat())
    
    # Dataset for previous month
    prev_month_dt = datetime(year, month, 1) - timedelta(days=1)
    _add_dataset(setup_registry, dataset_version='m_v_prev', status='success', download_timestamp=prev_month_dt.isoformat())

    monthly_summary = get_monthly_summary(year, month, setup_registry.db_path)
    assert isinstance(monthly_summary, MonthlySummary)
    assert monthly_summary.year == year
    assert monthly_summary.month == month
    assert monthly_summary.total_ingestion_attempts == 2
    assert monthly_summary.successful_ingestions == 1
    assert monthly_summary.failed_ingestions == 1
    assert sorted(monthly_summary.datasets_processed) == ['m_v1', 'm_v2']
    assert monthly_summary.success_rate == 50.0

def test_get_historical_summary_empty(setup_registry):
    hist_summary = get_historical_summary(db_path=setup_registry.db_path)
    assert hist_summary.total_datasets == 0
    assert not hist_summary.dataset_versions

def test_get_historical_summary_with_data(setup_registry, mock_artifacts_dir):
    dt1 = datetime(2023, 1, 15)
    dt2 = datetime(2023, 2, 10)
    dt3 = datetime(2023, 2, 20)
    
    _add_dataset(setup_registry, dataset_version='h_v1', status='success', download_timestamp=dt1.isoformat(), file_size=100)
    _add_dataset(setup_registry, dataset_version='h_v2', status='failed', download_timestamp=dt2.isoformat(), file_size=200)
    _add_dataset(setup_registry, dataset_version='h_v3', status='success', download_timestamp=dt3.isoformat(), file_size=300)

    # Add quality artifact for h_v1
    _create_artifact_file(mock_artifacts_dir, 'h_v1', 'quality', 'report.json', {'summary': {'quality_score': 0.9}})
    # Add schema diff for h_v3
    _create_artifact_file(mock_artifacts_dir, 'h_v3', 'schema_diff', 'diff.json', {'missing': ['col_c'], 'extra': []})

    hist_summary = get_historical_summary('2023-01-01', '2023-03-01', setup_registry.db_path)
    assert isinstance(hist_summary, HistoricalSummary)
    assert hist_summary.total_datasets == 3
    assert hist_summary.successful_datasets == 2
    assert hist_summary.failed_datasets == 1
    assert hist_summary.total_file_size_bytes == 600
    assert hist_summary.avg_file_size_bytes == 200.0
    assert hist_summary.avg_quality_score == 0.9 # Only one quality score available

    assert len(hist_summary.monthly_summaries) == 2
    assert hist_summary.monthly_summaries[0].month_key == '2023-01'
    assert hist_summary.monthly_summaries[0].total_ingestion_attempts == 1
    assert hist_summary.monthly_summaries[1].month_key == '2023-02'
    assert hist_summary.monthly_summaries[1].total_ingestion_attempts == 2
    assert len(hist_summary.schema_changes_history) == 1
    assert hist_summary.schema_changes_history[0]['dataset_version'] == 'h_v3'
