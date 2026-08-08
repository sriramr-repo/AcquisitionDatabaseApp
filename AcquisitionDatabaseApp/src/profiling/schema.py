import duckdb
import pandas as pd
from typing import Dict, Any, List
from .base import BaseProfiler, ProfileResult


class SchemaProfiler(BaseProfiler):
    """Profiles column types, constraints, and patterns."""
    
    def profile(self, dataset_version: str, table_name: str, **kwargs) -> ProfileResult:
        conn = self.storage.get_connection()
        
        # Get table schema
        schema_info = conn.execute(f"DESCRIBE {table_name}").fetchall()
        columns = []
        
        for col in schema_info:
            col_name, col_type = col[0], col[1]
            
            # Get sample values for pattern detection
            sample = conn.execute(
                f"SELECT {col_name} FROM {table_name} WHERE {col_name} IS NOT NULL LIMIT 100"
            ).fetchall()
            sample_values = [str(r[0]) for r in sample]
            
            # Infer pattern
            pattern = self._infer_pattern(sample_values) if sample_values else None
            
            # Get null count
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE {col_name} IS NULL"
            ).fetchone()[0]
            
            total_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            
            columns.append({
                'name': col_name,
                'type': col_type,
                'nullable': null_count > 0,
                'null_count': null_count,
                'total_count': total_count,
                'null_percentage': round(null_count / total_count * 100, 2) if total_count > 0 else 0,
                'pattern': pattern,
                'sample_values': sample_values[:5]
            })
        
        conn.close()
        
        results = {
            'table_name': table_name,
            'column_count': len(columns),
            'row_count': total_count,
            'columns': columns
        }
        
        return ProfileResult(
            profiler_type='schema',
            table_name=table_name,
            results=results
        )
    
    def _infer_pattern(self, values: List[str]) -> str:
        """Infer regex pattern from sample values."""
        if not values:
            return None
        
        # Simple pattern detection
        all_digits = all(v.isdigit() for v in values)
        all_alpha = all(v.isalpha() for v in values)
        all_alnum = all(v.isalnum() for v in values)
        
        if all_digits:
            return '^\\d+$'
        elif all_alpha:
            return '^[A-Za-z]+$'
        elif all_alnum:
            return '^[A-Za-z0-9]+$'
        
        # Check for email-like
        if all('@' in v and '.' in v for v in values):
            return 'email'
        
        # Check for date-like
        import re
        date_pattern = re.compile(r'^\\d{4}-\\d{2}-\\d{2}$')
        if all(date_pattern.match(v) for v in values):
            return 'date_iso'
        
        return 'mixed'