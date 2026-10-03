import pytest
from click.testing import CliRunner
import sys
import os
sys.path.insert(0, 'src')
from cli import app
from pipeline import run_pipeline
from metadata import list_datasets, get_current_dataset
from unittest.mock import patch, MagicMock
import tempfile
from pathlib import Path

@pytest.fixture
def runner():
    return CliRunner()

def test_download_data_cli(runner, tmp_path):
    """Test download-data CLI command."""
    with patch('cli.run_pipeline') as mock_run:
        mock_run.return_value = {
            'dataset_version': 'ia07012026',
            'status': 'success',
            'dataset_name': 'ia07012026',
            'source_url': 'https://www.sec.gov/files/ia07012026.zip',
            'download_timestamp': '2024-01-01T00:00:00',
            'file_name': 'ia07012026.zip',
            'file_size': 1000,
            'sha256_checksum': 'abc123',
            'tables_loaded': 'dummy',
            'rows_loaded': 1,
            'execution_time': 1.0,
            'notes': ''
        }
        result = runner.invoke(app, ['download-data'])
        assert result.exit_code == 0
        assert 'ia07012026' in result.output
        assert 'successfully' in result.output.lower()

def test_download_data_cli_skipped(runner, tmp_path):
    """Test download-data CLI command when dataset already exists."""
    with patch('cli.run_pipeline') as mock_run:
        mock_run.return_value = {
            'dataset_version': 'ia07012026',
            'status': 'skipped',
            'dataset_name': 'ia07012026',
            'source_url': 'https://www.sec.gov/files/ia07012026.zip',
            'download_timestamp': '2024-01-01T00:00:00',
            'file_name': 'ia07012026.zip',
            'file_size': 1000,
            'sha256_checksum': 'abc123',
            'tables_loaded': 'dummy',
            'rows_loaded': 1,
            'execution_time': 1.0,
            'notes': 'Dataset already exists'
        }
        result = runner.invoke(app, ['download-data'])
        assert result.exit_code == 0
        assert 'ia07012026' in result.output
        assert 'already exists' in result.output

def test_force_refresh_cli(runner, tmp_path):
    """Test force-refresh CLI command."""
    with patch('cli.run_pipeline') as mock_run:
        mock_run.return_value = {
            'dataset_version': 'ia07012026',
            'status': 'success',
            'dataset_name': 'ia07012026',
            'source_url': 'https://www.sec.gov/files/ia07012026.zip',
            'download_timestamp': '2024-01-01T00:00:00',
            'file_name': 'ia07012026.zip',
            'file_size': 1000,
            'sha256_checksum': 'abc123',
            'tables_loaded': 'dummy',
            'rows_loaded': 1,
            'execution_time': 1.0,
            'notes': ''
        }
        result = runner.invoke(app, ['force-refresh'])
        assert result.exit_code == 0
        assert 'ia07012026' in result.output
        assert 'refreshed' in result.output.lower()

def test_list_datasets_cli(runner, tmp_path):
    """Test list-datasets CLI command."""
    with patch('cli.list_datasets') as mock_list:
        mock_list.return_value = [
            {'dataset_version': 'ia07012026', 'status': 'success', 'download_timestamp': '2024-01-01T00:00:00'},
            {'dataset_version': 'ia07012025', 'status': 'success', 'download_timestamp': '2023-01-01T00:00:00'},
        ]
        result = runner.invoke(app, ['list-datasets'])
        assert result.exit_code == 0
        assert 'ia07012026' in result.output
        assert 'ia07012025' in result.output

def test_list_datasets_cli_empty(runner, tmp_path):
    """Test list-datasets CLI command when empty."""
    with patch('cli.list_datasets') as mock_list:
        mock_list.return_value = []
        result = runner.invoke(app, ['list-datasets'])
        assert result.exit_code == 0
        # Empty output is fine

def test_show_current_cli(runner, tmp_path):
    """Test show-current CLI command."""
    with patch('cli.get_current_dataset') as mock_get:
        mock_get.return_value = {'dataset_version': 'ia07012026', 'status': 'success'}
        result = runner.invoke(app, ['show-current'])
        assert result.exit_code == 0
        assert 'ia07012026' in result.output

def test_show_current_cli_none(runner, tmp_path):
    """Test show-current CLI command when no dataset."""
    with patch('cli.get_current_dataset') as mock_get:
        mock_get.return_value = None
        result = runner.invoke(app, ['show-current'])
        assert result.exit_code == 0
        assert 'No dataset ingested' in result.output