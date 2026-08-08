import duckdb
import pandas as pd
from typing import Dict, Any, List
from .base import BaseProfiler, ProfileResult


class QualityProfiler(BaseProfiler):
    """Profiles data quality: nulls, duplicates, completeness."""
    
    def profile(self, dataset_version: str, table_name: str, **kwargs) -> ProfileResult:
        conn = self.storage.get_connection()
        
        # Get table statistics
        stats = {}
        
        # Row count and basic metrics
        result = conn.execute(f"""
            SELECT 
                COUNT(*) as total_rows,
                COUNT(*) - COUNT(*) FILTER (WHERE * IS NULL) as non_null_rows,
                COUNT(DISTINCT *) as unique_rows,
                COUNT(*) FILTER (WHERE 1=1) as total_cells,
                COUNT(*) FILTER (WHERE * IS NULL) as null_cells
            FROM {table_name}
        """).fetchone()
        
        stats['total_rows'] = result[0]
        stats['total_cells'] = result[3]
        stats['null_cells'] = result[4]
        stats['non_null_cells'] = result[3] - result[4]
        
        # Calculate percentages
        if result[0] > 0:
            stats['null_percentage'] = round(result[4] / (result[3] * result[0]) * 100, 2)
        else:
            stats['null_percentage'] = 0
        
        # Duplicate detection (sample for performance)
        try:
            duplicates = conn.execute(f"""
                SELECT COUNT(*) as duplicate_count FROM (
                    SELECT *, COUNT(*) as cnt FROM {table_name}
                    GROUP BY *
                    HAVING cnt > 1
                ) as dup
            """).fetchone()[0]
            stats['estimated_duplicate_rows'] = duplicates
        except Exception:
            stats['estimated_duplicate_rows'] = 0
        
        # Column-level quality metrics
        columns = conn.execute(f"DESCRIBE {table_name}").fetchall()
        column_stats = []
        
        for col_name, col_type in columns:
            try:
                # Null count
                null_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE {col_name} IS NULL"
                ).fetchone()[0]
                
                # Empty string count for text columns
                empty_count = 0
                if col_type.lower() in ['varchar', 'text', 'char']:
                    empty_count = conn.execute(
                        f"SELECT COUNT(*) FROM {table_name} WHERE TRIM({col_name}) = '' OR {col_name} IS NULL"
                    ).fetchone()[0]
                
                # Zero values for numeric columns
                zero_count = 0
                if col_type.lower() in ['integer', 'decimal', 'numeric', 'real']:
                    zero_count = conn.execute(
                        f"SELECT COUNT(*) FROM {table_name} WHERE CAST({col_name} AS REAL) = 0"
                    ).fetchone()[0]
                
                # Unique values
                unique_count = conn.execute(
                    f"SELECT COUNT(DISTINCT {col_name}) FROM {table_name} WHERE {col_name} IS NOT NULL"
                ).fetchone()[0]
                
                total_non_null = stats['total_rows'] - null_count
                
                column_stats.append({
                    'name': col_name,
                    'type': col_type,
                    'null_count': null_count,
                    'empty_count': empty_count,
                    'zero_count': zero_count,
                    'unique_values': unique_count,
                    'completeness_percentage': round(
                        (total_non_null / stats['total_rows']) * 100, 2
                    ) if stats['total_rows'] > 0 else 0,
                    'distinctiveness_ratio': round(
                        unique_count / total_non_null * 100, 2
                    ) if total_non_null > 0 else 0
                })
            except Exception as e:
                column_stats.append({
                    'name': col_name,
                    'type': col_type,
                    'error': str(e)
                })
        
        stats['column_quality'] = column_stats
        stats['quality_score'] = self._calculate_quality_score(stats)
        
        conn.close()
        
        return ProfileResult(
            profiler_type='quality',
            table_name=table_name,
            results=stats
        )
    
    def _calculate_quality_score(self, stats: Dict[str, Any]) -> float:
        """Calculate overall quality score (0-100)."""
        score_components = []
        
        # Completeness component (40% weight)
        completeness = 100 - stats.get('null_percentage', 0)
        score_components.append(completeness * 0.4)
        
        # Uniqueness component (30% weight)
        unique_ratio = 0
        total_rows = stats.get('total_rows', 1)
        if total_rows > 0:
            unique_rows = conn.execute(f"SELECT COUNT(DISTINCT *) FROM {table_name}").fetchone()[0]
            unique_ratio = (unique_rows / total_rows) * 100
        score_components.append(unique_ratio * 0.3)
        
        # Completeness component (20% weight)
        avg_column_completeness = sum(
            col.get('completeness_percentage', 0) 
            for col in stats.get('column_quality', [])
        ) / len(stats.get('column_quality', [])) if stats.get('column_quality') else 0
        score_components.append(avg_column_completeness * 0.2)
        
        # Distinctiveness component (10% weight)
        avg_distinctiveness = sum(
            col.get('distinctiveness_ratio', 0) 
            for col in stats.get('column_quality', [])
            if 'distinctiveness_ratio' in col
        ) / len([col for col in stats.get('column_quality', []) if 'distinctiveness_ratio' in col]) if stats.get('column_quality') else 0
        score_components.append(avg_distinctiveness * 0.1)
        
        return round(sum(score_components), 2)