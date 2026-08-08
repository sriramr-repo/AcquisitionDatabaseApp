import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SEC_INDEX_URL: str = "https://www.sec.gov/data-research/sec-markets-data/information-about-registered-investment-advisers-exempt-reporting-advisers"
    FALLBACK_URL: str = "https://www.sec.gov/files/investment/data/other/information-about-registered-investment-advisers-exempt-reporting-advisers/ia07012026.zip"
    
    # Medallion architecture
    BASE_DIR: Path = Path("data")
    BRONZE_DIR: Path = BASE_DIR / "bronze"
    SILVER_DIR: Path = BASE_DIR / "silver"
    GOLD_DIR: Path = BASE_DIR / "gold"
    ARCHIVE_DIR: Path = BASE_DIR / "archive"
    EXPORTS_DIR: Path = BASE_DIR / "exports"
    LOG_DIR: Path = BASE_DIR / "logs"
    
    # Legacy paths (backward compat — these now point into bronze)
    RAW_DIR: Path = BRONZE_DIR / "raw"
    
    # SQLite — metadata only
    DB_FILE: Path = BASE_DIR / "metadata.db"
    DB_PATH: str = f"sqlite:///{DB_FILE}"
    
    # DuckDB — analytical workloads
    DUCKDB_FILE: Path = BASE_DIR / "analytics.duckdb"
    
    # Pipeline settings
    RETRY_ATTEMPTS: int = 3
    TIMEOUT: int = 30
    USER_AGENT: str = "Mozilla/5.0 (compatible; SECDataPipeline/1.0)"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for path in [
            self.BRONZE_DIR, self.SILVER_DIR, self.GOLD_DIR,
            self.ARCHIVE_DIR, self.EXPORTS_DIR, self.LOG_DIR
        ]:
            path.mkdir(parents=True, exist_ok=True)

settings = Settings()