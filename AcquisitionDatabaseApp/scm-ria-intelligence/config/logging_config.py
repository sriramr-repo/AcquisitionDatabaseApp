"\"\"\"Logging configuration for the application.\"\"\"

import logging
import sys
from pathlib import Path
from typing import Optional

from config.settings import settings


def setup_logging(log_file: Optional[Path] = None, log_level: str = "INFO") -> None:
    \"\"\"Set up application logging configuration.
    
    Args:
        log_file: Optional path to log file. If None, logs only to console.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    \"\"\"
    # Convert string level to logging constant
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    simple_formatter = logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (if log_file specified)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)
    
    # Set logging levels for external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    \"\"\"Get a logger instance for a module.
    
    Args:
        name: Name of the module (usually __name__).
    
    Returns:
        Configured logger instance.
    \"\"\"
    return logging.getLogger(name)


# Initialize logging on import
setup_logging(
    log_file=settings.LOG_FILE,
    log_level=settings.LOG_LEVEL
)"