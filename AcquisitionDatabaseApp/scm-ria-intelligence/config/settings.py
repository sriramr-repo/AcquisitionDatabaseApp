"\"\"\"Application settings and configuration.\"\"\"

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Settings:
    \"\"\"Application settings singleton.\"\"\"

    # Project paths
    PROJECT_ROOT = Path(__file__).parent.parent
    DATA_DIR = PROJECT_ROOT / "data"
    CONFIG_DIR = PROJECT_ROOT / "config"
    LOGS_DIR = PROJECT_ROOT / "logs"
    EXPORTS_DIR = PROJECT_ROOT / "data" / "exports"
    
    # Database settings
    DATABASE_PATH: Path = Path(os.getenv("DATABASE_PATH", "./data/database/ria_intelligence.db"))
    DATABASE_BACKUP_DIR: Path = Path(os.getenv("DATABASE_BACKUP_DIR", "./data/database/backups/"))
    
    # SEC settings
    SEC_DATA_URL: str = os.getenv("SEC_DATA_URL", "https://www.sec.gov/files/other/ria/adv.zip")
    SEC_DATA_REFRESH_DAYS: int = int(os.getenv("SEC_DATA_REFRESH_DAYS", "90"))
    
    # Application settings
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Optional[Path] = Path(os.getenv("LOG_FILE", "./logs/app.log")) if os.getenv("LOG_FILE") else None
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "4"))
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    RETRY_ATTEMPTS: int = int(os.getenv("RETRY_ATTEMPTS", "3"))
    
    # Export settings
    EXPORT_FORMAT: str = os.getenv("EXPORT_FORMAT", "xlsx")
    EXPORT_DIR: Path = Path(os.getenv("EXPORT_DIR", "./data/exports/"))
    REPORT_TEMPLATE_DIR: Path = Path(os.getenv("REPORT_TEMPLATE_DIR", "./config/templates/"))
    
    # Scoring settings
    SCORING_WEIGHTS_JSON: Path = Path(os.getenv("SCORING_WEIGHTS_JSON", "./config/scoring_weights.json"))
    MIN_SCORE_THRESHOLD: int = int(os.getenv("MIN_SCORE_THRESHOLD", "50"))
    MAX_CANDIDATES_PER_REPORT: int = int(os.getenv("MAX_CANDIDATES_PER_REPORT", "100"))
    
    # Research settings
    RESEARCH_CACHE_ENABLED: bool = os.getenv("RESEARCH_CACHE_ENABLED", "true").lower() == "true"
    RESEARCH_CACHE_DIR: Path = Path(os.getenv("RESEARCH_CACHE_DIR", "./data/research_cache/"))
    RESEARCH_SESSION_TIMEOUT: int = int(os.getenv("RESEARCH_SESSION_TIMEOUT", "3600"))
    
    # Development settings
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    TEST_DATABASE_PATH: Path = Path(os.getenv("TEST_DATABASE_PATH", "./data/database/test.db"))
    ENABLE_METRICS: bool = os.getenv("ENABLE_METRICS", "true").lower() == "true"
    
    def __init__(self) -> None:
        \"\"\"Initialize and validate settings.\"\"\"
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        \"\"\"Ensure required directories exist.\"\"\"
        directories = [
            self.DATA_DIR,
            self.DATA_DIR / "raw",
            self.DATA_DIR / "processed",
            self.DATA_DIR / "exports",
            self.DATA_DIR / "database",
            self.DATABASE_BACKUP_DIR,
            self.CONFIG_DIR,
            self.LOGS_DIR,
            self.EXPORTS_DIR,
            self.RESEARCH_CACHE_DIR,
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()"