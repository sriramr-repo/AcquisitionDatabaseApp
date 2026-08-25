import hashlib
import logging
import os
import re
import tempfile
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from src.config import settings


log = logging.getLogger(__name__)

_last_discovery: dict[str, object] = {
    "discovery_source": "unknown",
    "fallback_used": False,
    "discovery_error": None,
}

_SEC_HEADER_SIGNATURES = ("organization crd#", "primary business name")
_OBVIOUS_NON_ZIP_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "text/xml",
    "application/json",
    "application/xml",
)


def get_latest_url() -> str:
    """Return the latest URL while retaining discovery provenance for operations."""
    global _last_discovery
    _last_discovery = {"discovery_source": "primary", "fallback_used": False, "discovery_error": None}
    try:
        resp = requests.get(
            settings.SEC_INDEX_URL,
            headers={"User-Agent": settings.USER_AGENT},
            timeout=settings.TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for link in soup.find_all("a", href=True):
            if re.search(r"ia\d{8}\.zip", link["href"]):
                log.info(f"Found latest SEC ZIP URL: {link['href']}")
                url = f"https://www.sec.gov{link['href']}" if link["href"].startswith("/") else link["href"]
                _last_discovery = {"discovery_source": "primary", "fallback_used": False, "discovery_error": None}
                return url
    except requests.exceptions.RequestException as exc:
        log.error(f"Network or HTTP error fetching SEC index: {exc}")
        _last_discovery = {"discovery_source": "fallback", "fallback_used": True, "discovery_error": str(exc)}
    except Exception as exc:
        log.error(f"An unexpected error occurred in get_latest_url: {exc}")
        _last_discovery = {"discovery_source": "fallback", "fallback_used": True, "discovery_error": str(exc)}
    else:
        _last_discovery = {"discovery_source": "fallback", "fallback_used": True,
                           "discovery_error": "SEC index contained no IA ZIP link"}
    log.warning(f"Could not find latest URL, using fallback: {settings.FALLBACK_URL}")
    return settings.FALLBACK_URL


def get_discovery_status() -> dict[str, object]:
    """Return provenance for the most recent discovery call."""
    return dict(_last_discovery)


def _has_sec_data_signature(path: Path) -> bool:
    """Check for the stable Form ADV header fields in a CSV ZIP member."""
    with zipfile.ZipFile(path, "r") as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.lower().endswith(".csv"):
                continue
            with archive.open(member) as stream:
                header = stream.read(8192).decode("utf-8-sig", errors="replace").splitlines()[0].lower()
            if all(signature in header for signature in _SEC_HEADER_SIGNATURES):
                return True
    return False


def _validate_sec_zip(path: Path) -> bool:
    """Validate ZIP structure, readable members, and SEC IA semantics."""
    if not path.is_file() or path.stat().st_size == 0 or not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if not members or archive.testzip() is not None:
                return False
            for member in members:
                with archive.open(member) as stream:
                    stream.read(1)
        return _has_sec_data_signature(path)
    except (OSError, ValueError, zipfile.BadZipFile, IndexError):
        return False


def _response_content_type(response: requests.Response) -> str:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
    return value.lower().split(";", 1)[0].strip() if isinstance(value, str) else ""


def _download_to_temp(url: str, dest: Path) -> tuple[Path, str]:
    """Stream a response into a same-directory temporary file and validate it."""
    response = requests.get(
        url,
        headers={"User-Agent": settings.USER_AGENT},
        timeout=settings.TIMEOUT,
        stream=True,
        allow_redirects=True,
    )
    response.raise_for_status()

    content_type = _response_content_type(response)
    if content_type in _OBVIOUS_NON_ZIP_CONTENT_TYPES:
        raise ValueError(f"Unexpected download Content-Type: {content_type}")

    headers = getattr(response, "headers", {}) or {}
    expected_length = headers.get("Content-Length") if hasattr(headers, "get") else None
    if isinstance(expected_length, (str, int)) and not isinstance(expected_length, bool):
        try:
            expected_length = int(expected_length)
        except ValueError:
            expected_length = None
    else:
        expected_length = None

    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    digest = hashlib.sha256()
    received = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{dest.name}.",
            suffix=".part",
            dir=dest.parent,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                temp_file.write(chunk)
                digest.update(chunk)
                received += len(chunk)

        if received == 0:
            raise ValueError("Downloaded response body is empty")
        if expected_length is not None and expected_length != received:
            raise ValueError(f"Downloaded size mismatch: expected {expected_length}, received {received}")
        if not _validate_sec_zip(temp_path):
            raise ValueError("Downloaded file is not a valid SEC IA ZIP")
        return temp_path, digest.hexdigest()
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def download_zip(url: str, dest: Path) -> str:
    """Download and atomically install a validated SEC IA ZIP."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and _validate_sec_zip(dest):
        digest = hashlib.sha256()
        with dest.open("rb") as existing_file:
            for chunk in iter(lambda: existing_file.read(1024 * 1024), b""):
                digest.update(chunk)
        log.info(f"Validated existing SEC ZIP at {dest}; skipping download.")
        return digest.hexdigest()

    if dest.exists():
        log.warning(f"Existing file at {dest} failed SEC ZIP validation; downloading replacement safely.")

    last_error = None
    for attempt in range(settings.RETRY_ATTEMPTS):
        try:
            log.info(f"Downloading {url} (attempt {attempt + 1}/{settings.RETRY_ATTEMPTS})...")
            temp_path, checksum = _download_to_temp(url, dest)
            os.replace(temp_path, dest)
            log.info(f"Validated download installed at {dest}.")
            return checksum
        except requests.exceptions.RequestException as exc:
            last_error = exc
            log.warning(f"Download attempt {attempt + 1} failed for {url}: {exc}")
        except Exception as exc:
            last_error = exc
            log.warning(f"Download validation attempt {attempt + 1} failed for {url}: {exc}")

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Download failed for {url}")
