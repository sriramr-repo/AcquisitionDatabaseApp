import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import requests

# We assume the project structure has src as a package
# Adjust the import if necessary
import sys
sys.path.append('src')
from download import get_latest_url, download_zip
from config import settings

def test_get_latest_url():
    # Mock the SEC index page to return a known URL
    with patch('requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/files/ia07012026.zip">Download</a>'
        mock_get.return_value = mock_response
        url = get_latest_url()
        assert 'ia07012026.zip' in url
        assert url.startswith('https://www.sec.gov')

def test_download_zip(tmp_path):
    # Mock the download to create a fake ZIP file
    fake_zip_content = b'fake zip content'
    with patch('requests.get') as mock_get:
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [fake_zip_content]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        dest = tmp_path / 'test.zip'
        checksum = download_zip('http://example.com/test.zip', dest)
        assert dest.exists()
        assert len(checksum) == 64  # SHA256 hex digest
