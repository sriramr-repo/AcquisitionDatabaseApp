import pandas as pd
import duckdb
from pathlib import Path
from typing import Dict, Any, List, Tuple
from src.config import settings
from src.storage import StorageManager, PathResolver

storage = StorageManager()

def load_to_dataframes(extracted_dir: Path) -> Dict[str, pd.DataFrame]:
    frames = {}
    for csv in extracted_dir.iterdir():
        if csv.suffix.lower() == '.csv':
            df = pd.read_csv(csv, dtype=str, encoding='latin-1')
            frames[csv.stem] = df
    return frames

def save_to_db(df_dict: Dict[str, pd.DataFrame], dataset_version: str) -> Tuple[List[str], int]:
    conn = storage.get_connection()
    tables_loaded = []
    rows_total = 0
    
    for name, df in df_dict.items():
        # Sanitize table and registration names: replace hyphens with underscores
        safe_name = name.replace('-', '_')
        table_name = f"bronze_raw_{safe_name}_{dataset_version.replace('-', '')}"
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        # Register with underscore-safe name
        conn.register(f"df_{safe_name}", df)
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df_{safe_name}")
        conn.unregister(f"df_{safe_name}") # Unregister after use
        rows_total += len(df)
        tables_loaded.append(table_name)
        
    conn.close()
    return tables_loaded, rows_total


def write_silver(normalized: Dict[str, list], dataset_version: str) -> Tuple[List[str], int]:
    """Write normalized Pydantic models to silver DuckDB tables."""
    conn = storage.get_connection()
    tables_written = []
    rows_total = 0

    entity_map = {
        "firms": "firms",
        "offices": "firm_offices",
        "acquired_firms": "firm_acquired_firms"
    }

    for key, table_suffix in entity_map.items():
        records = normalized.get(key, [])
        if not records:
            continue

        table_name = PathResolver.silver_table(table_suffix, dataset_version)
        df = pd.DataFrame([r.model_dump() for r in records])

        # Convert datetime/Decimal for DuckDB
        for col in df.columns:
            if df[col].dtype == 'object':
                sample = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
                if hasattr(sample, 'isoformat'):
                    df[col] = df[col].apply(lambda x: x.isoformat() if hasattr(x, 'isoformat') else x)
                elif hasattr(sample, '__float__'):
                    df[col] = df[col].apply(lambda x: float(x) if x is not None else None)

        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.register(f"df_{key}", df)
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df_{key}")
        conn.unregister(f"df_{key}")

        rows_total += len(df)
        tables_written.append(table_name)

    conn.close()
    return tables_written, rows_total
