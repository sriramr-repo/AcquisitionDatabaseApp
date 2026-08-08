"\"\"\"Database connection and management utilities.\"\"\"

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from config.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)


class DatabaseConnection:
    \"\"\"Manages SQLite database connections with connection pooling.
    
    Attributes:
        db_path: Path to the SQLite database file.
        read_only: Whether to open the database in read-only mode.
    \"\"\"
    
    def __init__(self, db_path: Optional[Path] = None, read_only: bool = False) -> None:
        \"\"\"Initialize database connection manager.
        
        Args:
            db_path: Path to SQLite database file. Uses settings.DATABASE_PATH if None.
            read_only: Open database in read-only mode.
        \"\"\"
        self.db_path = db_path or settings.DATABASE_PATH
        self.read_only = read_only
        
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.debug(f"Database connection initialized for: {self.db_path}")
    
    @contextmanager
    def get_connection(self) -> Iterator[sqlite3.Connection]:
        \"\"\"Get a database connection as a context manager.
        
        Yields:
            SQLite database connection.
            
        Raises:
            sqlite3.Error: If connection cannot be established.
        \"\"\"
        connection = None
        try:
            if self.read_only and self.db_path.exists():
                uri = f"file:{self.db_path}?mode=ro"
                connection = sqlite3.connect(uri, uri=True)
            else:
                connection = sqlite3.connect(str(self.db_path))
            
            # Configure connection
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            
            logger.debug(f"Database connection established: {self.db_path}")
            yield connection
            
        except sqlite3.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if connection:
                connection.close()
                logger.debug("Database connection closed")
    
    @contextmanager
    def get_cursor(self) -> Iterator[sqlite3.Cursor]:
        \"\"\"Get a database cursor as a context manager.
        
        Yields:
            SQLite database cursor.
        \"\"\"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
    
    def execute_query(self, query: str, parameters: tuple = ()) -> list:
        \"\"\"Execute a read-only query and return results.
        
        Args:
            query: SQL query string.
            parameters: Query parameters.
            
        Returns:
            List of query results.
        \"\"\"
        with self.get_cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchall()
    
    def execute_script(self, script: str) -> None:
        \"\"\"Execute a SQL script.
        
        Args:
            script: SQL script to execute.
        \"\"\"
        with self.get_connection() as conn:
            conn.executescript(script)
            conn.commit()
    
    def table_exists(self, table_name: str) -> bool:
        \"\"\"Check if a table exists in the database.
        
        Args:
            table_name: Name of the table to check.
            
        Returns:
            True if table exists, False otherwise.
        \"\"\"
        query = \"\"\"
        SELECT COUNT(*) 
        FROM sqlite_master 
        WHERE type='table' AND name=?
        \"\"\"
        
        result = self.execute_query(query, (table_name,))
        return result[0][0] > 0 if result else False
    
    def get_table_info(self, table_name: str) -> list:
        \"\"\"Get information about a table's columns.
        
        Args:
            table_name: Name of the table.
            
        Returns:
            List of column information dictionaries.
        \"\"\"
        if not self.table_exists(table_name):
            return []
        
        query = f"PRAGMA table_info({table_name})"
        return self.execute_query(query)
    
    def backup_database(self, backup_path: Optional[Path] = None) -> Path:
        \"\"\"Create a backup of the database.
        
        Args:
            backup_path: Path for backup file. Uses settings.DATABASE_BACKUP_DIR if None.
            
        Returns:
            Path to the backup file.
            
        Raises:
            FileNotFoundError: If database file doesn't exist.
            sqlite3.Error: If backup fails.
        \"\"\"
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {self.db_path}")
        
        backup_dir = backup_path or settings.DATABASE_BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"ria_intelligence_backup_{timestamp}.db"
        
        try:
            with self.get_connection() as source:
                with sqlite3.connect(str(backup_file)) as backup:
                    source.backup(backup)
            
            logger.info(f"Database backup created: {backup_file}")
            return backup_file
            
        except sqlite3.Error as e:
            logger.error(f"Database backup failed: {e}")
            raise


# Global database connection instance
db_connection = DatabaseConnection()

# Test database connection for development
test_db_connection = DatabaseConnection(settings.TEST_DATABASE_PATH)


# Import datetime for backup method
from datetime import datetime"