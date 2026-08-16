"""Quality profiler for the SCM RIA platform."""

from typing import Dict, Any

from .base import BaseProfiler, ProfileResult


class QualityProfiler(BaseProfiler):
    """Profiles data quality: nulls, duplicates, completeness."""

    def profile(self, dataset_version: str, table_name: str, **kwargs) -> ProfileResult:
        conn = self.storage.get_connection()

        # Get table statistics
        stats = {}

        # Row count
        row_result = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        total_rows = row_result[0] if row_result else 0
        stats["total_rows"] = total_rows

        # Column-level quality metrics
        columns = conn.execute(f"DESCRIBE {table_name}").fetchall()
        column_stats = []
        total_cells = 0
        null_cells = 0

        for col_name, col_type, *_ in columns:
            try:
                null_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table_name} WHERE {col_name} IS NULL"
                ).fetchone()[0]

                empty_count = 0
                if col_type.lower() in ["varchar", "text", "char"]:
                    empty_count = conn.execute(
                        f"SELECT COUNT(*) FROM {table_name} WHERE TRIM({col_name}) = '' OR {col_name} IS NULL"
                    ).fetchone()[0]

                zero_count = 0
                if col_type.lower() in ["integer", "decimal", "numeric", "real"]:
                    zero_count = conn.execute(
                        f"SELECT COUNT(*) FROM {table_name} WHERE CAST({col_name} AS REAL) = 0"
                    ).fetchone()[0]

                unique_count = conn.execute(
                    f"SELECT COUNT(DISTINCT {col_name}) FROM {table_name} WHERE {col_name} IS NOT NULL"
                ).fetchone()[0]

                total_non_null = total_rows - null_count

                column_stats.append({
                    "name": col_name,
                    "type": col_type,
                    "null_count": null_count,
                    "empty_count": empty_count,
                    "zero_count": zero_count,
                    "unique_values": unique_count,
                    "completeness_percentage": round(
                        (total_non_null / total_rows) * 100, 2
                    ) if total_rows > 0 else 0,
                    "distinctiveness_ratio": round(
                        unique_count / total_non_null * 100, 2
                    ) if total_non_null > 0 else 0,
                })
                total_cells += total_rows
                null_cells += null_count
            except Exception as exc:
                column_stats.append({
                    "name": col_name,
                    "type": col_type,
                    "error": str(exc),
                })

        stats["column_quality"] = column_stats
        stats["total_cells"] = total_cells
        stats["null_cells"] = null_cells
        stats["non_null_cells"] = total_cells - null_cells

        # Calculate percentages
        if total_cells > 0:
            stats["null_percentage"] = round(null_cells / total_cells * 100, 2)
        else:
            stats["null_percentage"] = 0

        # Duplicate detection
        try:
            col_list = ", ".join(c[0] for c in columns)
            duplicate_result = conn.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT {col_list}, COUNT(*) AS cnt FROM {table_name}
                    GROUP BY {col_list}
                    HAVING cnt > 1
                ) AS dup
                """
            ).fetchone()
            stats["estimated_duplicate_rows"] = duplicate_result[0]
        except Exception:
            stats["estimated_duplicate_rows"] = 0

        stats["quality_score"] = self._calculate_quality_score(
            stats, conn, table_name
        )

        conn.close()

        return ProfileResult(
            profiler_type="quality",
            table_name=table_name,
            results=stats,
        )

    def _calculate_quality_score(
        self, stats: Dict[str, Any], conn, table_name: str
    ) -> float:
        """Calculate overall quality score (0-100)."""
        score_components = []

        # Completeness component (40% weight)
        completeness = 100 - stats.get("null_percentage", 0)
        score_components.append(completeness * 0.4)

        # Uniqueness component (30% weight)
        unique_ratio = 0
        total_rows = stats.get("total_rows", 1)
        if total_rows > 0:
            unique_row_result = conn.execute(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {table_name})"
            ).fetchone()
            unique_rows = unique_row_result[0]
            unique_ratio = (unique_rows / total_rows) * 100
        score_components.append(unique_ratio * 0.3)

        # Column completeness component (20% weight)
        column_quality = stats.get("column_quality", [])
        if column_quality:
            avg_column_completeness = sum(
                col.get("completeness_percentage", 0)
                for col in column_quality
            ) / len(column_quality)
        else:
            avg_column_completeness = 0
        score_components.append(avg_column_completeness * 0.2)

        # Distinctiveness component (10% weight)
        distinctiveness_values = [
            col.get("distinctiveness_ratio", 0)
            for col in column_quality
            if "distinctiveness_ratio" in col
        ]
        if distinctiveness_values:
            avg_distinctiveness = sum(distinctiveness_values) / len(
                distinctiveness_values
            )
        else:
            avg_distinctiveness = 0
        score_components.append(avg_distinctiveness * 0.1)

        return round(sum(score_components), 2)