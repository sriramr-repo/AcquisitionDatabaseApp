import hashlib
import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.config import settings
from src.download import download_zip, get_latest_url


SEC_HEADER = '"Organization CRD#","Primary Business Name"\n"1","Example RIA"\n'


class MockResponse:
    def __init__(self, body=b"", status_code=200, content_type="application/zip"):
        self.body = body
        self.status_code = status_code
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size=8192):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class PartialResponse(MockResponse):
    def iter_content(self, chunk_size=8192):
        yield self.body[:10]
        raise requests.ConnectionError("connection interrupted during response body")


def make_sec_zip(member_name="IA_SEC_-_FIRM_ROSTER_FOIA_DOWNLOAD_-_TEST.CSV", content=SEC_HEADER):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return output.getvalue()


def make_dummy_zip():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("dummy.csv", "col1,col2\nvalue1,value2")
    return output.getvalue()


def write_bytes(path: Path, body: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def assert_no_temp_parts(path: Path):
    assert list(path.parent.glob(f".{path.name}.*.part")) == []


def test_get_latest_url():
    with patch("src.download.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = '<a href="/files/ia07012026.zip">Download</a>'
        mock_get.return_value = mock_response

        url = get_latest_url()

    assert url == "https://www.sec.gov/files/ia07012026.zip"


def test_downloads_and_validates_sec_zip_atomically(tmp_path):
    body = make_sec_zip()
    destination = tmp_path / "nested" / "download.zip"

    with patch("src.download.requests.get", return_value=MockResponse(body)):
        checksum = download_zip("https://example.test/download.zip", destination)

    assert checksum == hashlib.sha256(body).hexdigest()
    assert destination.read_bytes() == body
    assert zipfile.is_zipfile(destination)
    assert_no_temp_parts(destination)


def test_existing_valid_zip_is_reused_without_network_call(tmp_path):
    body = make_sec_zip()
    destination = tmp_path / "download.zip"
    write_bytes(destination, body)

    with patch("src.download.requests.get") as mock_get:
        checksum = download_zip("https://example.test/download.zip", destination)

    mock_get.assert_not_called()
    assert checksum == hashlib.sha256(body).hexdigest()
    assert destination.read_bytes() == body


def test_invalid_existing_zip_is_replaced_only_after_valid_download(tmp_path):
    old_body = b"not a zip"
    new_body = make_sec_zip(content=SEC_HEADER.replace("Example RIA", "Replacement RIA"))
    destination = tmp_path / "download.zip"
    write_bytes(destination, old_body)

    with patch("src.download.requests.get", return_value=MockResponse(new_body)):
        download_zip("https://example.test/download.zip", destination)

    assert destination.read_bytes() == new_body
    assert_no_temp_parts(destination)


@pytest.mark.parametrize(
    "response, expected_exception",
    [
        (MockResponse(b"", content_type="application/zip"), ValueError),
        (MockResponse(b"not a zip", content_type="application/zip"), ValueError),
        (MockResponse(make_dummy_zip(), content_type="application/zip"), ValueError),
        (MockResponse(b"<html>access denied</html>", content_type="text/html"), ValueError),
    ],
)
def test_invalid_downloads_do_not_create_destination_or_leave_temp_files(
    tmp_path, response, expected_exception
):
    destination = tmp_path / "download.zip"

    with patch.object(settings, "RETRY_ATTEMPTS", 1), patch(
        "src.download.requests.get", return_value=response
    ), pytest.raises(expected_exception):
        download_zip("https://example.test/download.zip", destination)

    assert not destination.exists()
    assert_no_temp_parts(destination)


def test_http_failure_preserves_existing_destination(tmp_path):
    body = b"previous invalid placeholder"
    destination = tmp_path / "download.zip"
    write_bytes(destination, body)
    response = MockResponse(b"server error", status_code=500, content_type="text/plain")

    with patch.object(settings, "RETRY_ATTEMPTS", 1), patch(
        "src.download.requests.get", return_value=response
    ), pytest.raises(requests.HTTPError):
        download_zip("https://example.test/download.zip", destination)

    assert destination.read_bytes() == body
    assert_no_temp_parts(destination)


def test_network_failure_preserves_existing_file_and_cleans_partial_temp(tmp_path):
    old_body = b"previous bytes"
    destination = tmp_path / "download.zip"
    write_bytes(destination, old_body)

    with patch.object(settings, "RETRY_ATTEMPTS", 1), patch(
        "src.download.requests.get", side_effect=requests.ConnectionError("connection interrupted")
    ), pytest.raises(requests.ConnectionError):
        download_zip("https://example.test/download.zip", destination)

    assert destination.read_bytes() == old_body
    assert_no_temp_parts(destination)


def test_partial_response_preserves_existing_file_and_cleans_partial_temp(tmp_path):
    old_body = b"previous invalid placeholder"
    destination = tmp_path / "download.zip"
    write_bytes(destination, old_body)

    with patch.object(settings, "RETRY_ATTEMPTS", 1), patch(
        "src.download.requests.get", return_value=PartialResponse(make_sec_zip())
    ), pytest.raises(requests.ConnectionError):
        download_zip("https://example.test/download.zip", destination)

    assert destination.read_bytes() == old_body
    assert_no_temp_parts(destination)


def test_content_length_mismatch_preserves_existing_file(tmp_path):
    old_body = b"previous invalid placeholder"
    destination = tmp_path / "download.zip"
    write_bytes(destination, old_body)
    response = MockResponse(make_sec_zip(content=SEC_HEADER.replace("Example RIA", "New RIA")))
    response.headers["Content-Length"] = "1"

    with patch.object(settings, "RETRY_ATTEMPTS", 1), patch(
        "src.download.requests.get", return_value=response
    ), pytest.raises(ValueError, match="size mismatch"):
        download_zip("https://example.test/download.zip", destination)

    assert destination.read_bytes() == old_body
    assert_no_temp_parts(destination)
