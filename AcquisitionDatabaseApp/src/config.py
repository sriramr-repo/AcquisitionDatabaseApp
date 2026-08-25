import os
from pathlib import Path
from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    # Explicit environment separation.  Paths are rooted at the repository
    # location (or SCM_DATA_DIR), never at the caller's current directory.
    ENVIRONMENT: str = os.getenv("SCM_ENV", "DEV").upper()
    PROJECT_ROOT: Path = PROJECT_ROOT
    DATA_ROOT: Path = Path(os.getenv("SCM_DATA_DIR", ""))
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
    BACKUP_DIR: Path = BASE_DIR / "backups"
    RUN_MANIFEST_DIR: Path = BASE_DIR / "run_manifests"
    
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
        if not kwargs.get("DATA_ROOT"):
            env = os.getenv("SCM_ENV", "DEV").upper()
            explicit_root = os.getenv("SCM_DATA_DIR")
            root = Path(explicit_root).expanduser() if explicit_root else (
                PROJECT_ROOT / "data" if env == "PROD" else PROJECT_ROOT / f"data-{env.lower()}"
            )
            kwargs["DATA_ROOT"] = root
        root = Path(kwargs["DATA_ROOT"]).expanduser().resolve()
        kwargs["BASE_DIR"] = Path(kwargs.get("BASE_DIR", root)).expanduser().resolve()
        for name, default in {
            "BRONZE_DIR": root / "bronze", "SILVER_DIR": root / "silver",
            "GOLD_DIR": root / "gold", "ARCHIVE_DIR": root / "archive",
            "EXPORTS_DIR": root / "exports", "LOG_DIR": root / "logs",
            "BACKUP_DIR": root / "backups", "RUN_MANIFEST_DIR": root / "run_manifests",
            "RAW_DIR": root / "bronze" / "raw", "DB_FILE": root / "metadata.db",
            "DUCKDB_FILE": root / "analytics.duckdb",
        }.items():
            kwargs.setdefault(name, default)
        super().__init__(**kwargs)
        for path in [
            self.BRONZE_DIR, self.SILVER_DIR, self.GOLD_DIR,
            self.ARCHIVE_DIR, self.EXPORTS_DIR, self.LOG_DIR,
            self.BACKUP_DIR, self.RUN_MANIFEST_DIR,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "PROD"

    def assert_safe_path(self, path: Path, *, allow_production: bool = False) -> None:
        resolved = Path(path).expanduser().resolve()
        production_root = (PROJECT_ROOT / "data").resolve()
        if self.ENVIRONMENT != "PROD" and not allow_production and (
            resolved == production_root or production_root in resolved.parents
        ):
            raise RuntimeError(f"{self.ENVIRONMENT} environment cannot access production path: {resolved}")

settings = Settings()
