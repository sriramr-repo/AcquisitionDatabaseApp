import re
import hashlib
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from src.config import settings
import logging # Added

log = logging.getLogger(__name__) # Added

def get_latest_url() -> str:
    try:
        resp = requests.get(settings.SEC_INDEX_URL, headers={"User-Agent": settings.USER_AGENT}, timeout=settings.TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for link in soup.find_all('a', href=True):
            if re.search(r'ia\d{8}\.zip', link['href']):
                log.info(f"Found latest SEC ZIP URL: {link['href']}") # Added
                return f"https://www.sec.gov{link['href']}" if link['href'].startswith('/') else link['href']
    except requests.exceptions.RequestException as e: # Specific exception
        log.error(f"Network or HTTP error fetching SEC index: {e}") # Logged
    except Exception as e: # Catch all other unexpected errors
        log.error(f"An unexpected error occurred in get_latest_url: {e}") # Logged
    log.warning(f"Could not find latest URL, using fallback: {settings.FALLBACK_URL}") # Added
    return settings.FALLBACK_URL

def download_zip(url: str, dest: Path) -> str:
    if dest.exists() and dest.stat().st_size > 0: # Check if file exists, avoid re-downloading
        log.info(f"File already exists at {dest}, skipping download.")
        # ponytail: recalculate hash. ceiling: assume existing file is valid if non-empty. upgrade: re-hash file to confirm integrity.
        return "skipped_download_existing_file"

    for i in range(settings.RETRY_ATTEMPTS):
        try:
            log.info(f"Downloading {url} to {dest} (attempt {i+1}/{settings.RETRY_ATTEMPTS})...") # Added
            resp = requests.get(url, headers={"User-Agent": settings.USER_AGENT}, timeout=settings.TIMEOUT, stream=True)
            resp.raise_for_status()
            sha256 = hashlib.sha256()
            with open(dest, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    sha256.update(chunk)
            log.info(f"Download successful for {url}.") # Added
            return sha256.hexdigest()
        except requests.exceptions.RequestException as e: # Specific exception
            log.warning(f"Download attempt {i+1} failed for {url}: {e}") # Logged
            if i == settings.RETRY_ATTEMPTS - 1:
                log.error(f"All download attempts failed for {url}.") # Logged
                raise e
        except Exception as e: # Catch all other unexpected errors
            log.error(f"An unexpected error occurred during download of {url}: {e}") # Logged
            if i == settings.RETRY_ATTEMPTS - 1: raise e
    return ""