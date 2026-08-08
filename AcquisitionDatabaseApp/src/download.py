import re
import hashlib
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from src.config import settings

def get_latest_url() -> str:
    try:
        resp = requests.get(settings.SEC_INDEX_URL, headers={"User-Agent": settings.USER_AGENT}, timeout=settings.TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for link in soup.find_all('a', href=True):
            if re.search(r'ia\d{8}\.zip', link['href']):
                return f"https://www.sec.gov{link['href']}" if link['href'].startswith('/') else link['href']
    except Exception:
        pass
    return settings.FALLBACK_URL

def download_zip(url: str, dest: Path) -> str:
    for i in range(settings.RETRY_ATTEMPTS):
        try:
            resp = requests.get(url, headers={"User-Agent": settings.USER_AGENT}, timeout=settings.TIMEOUT, stream=True)
            resp.raise_for_status()
            sha256 = hashlib.sha256()
            with open(dest, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            if i == settings.RETRY_ATTEMPTS - 1: raise e
    return ""