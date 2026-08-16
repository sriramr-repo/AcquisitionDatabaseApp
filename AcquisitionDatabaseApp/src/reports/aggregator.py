"""
Core aggregation logic for reporting.
Consumes metadata.db and existing artifacts to build summaries.
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from collections import defaultdict

from src.config import settings
from src.storage import DatasetRegistry
from src.reports.models import (
    ExecutionSummary,
    DatasetSummary,
    MonthlySummary,
    HistoricalSummary,
)


def _get_registry(db_path: Optional[Path] = None) -> DatasetRegistry:
    """Get DatasetRegistry instance."""
    return DatasetRegistry(db_path or settings.DB_FILE)


def _load_artifacts_for_dataset(dataset_version: str) -> Dict[str, Any]:
    """Load all artifacts for a dataset version from disk."""
    artifacts = {}
    artifact_base = settings.BASE_DIR
    
    # Artifact types to look for
    artifact_types = [
        'profiling', 'validation', 'schema_diff', 'change_detection', 
        'quality', 'dictionary'
    ]
    
    for artifact_type in artifact_types:
        artifact_dir = artifact_base / artifact_type / dataset_version
        if artifact_dir.exists():
            artifacts[artifact_type] = []
            for json_file in artifact_dir.glob('*.json'):
                try:
                    with open(json_file, 'r') as f:
                        data = json.load(f)
                        data['_source_file'] = str(json_file)
                        data['_artifact_type'] = artifact_type
                        artifacts[artifact_type].append(data)
                except (json.JSONDecodeError, IOError):
                    pass
    return artifacts


def _extract_bronze_row_count(dataset_version: str) -> Optional[int]:
    """Get bronze row count from artifacts or metadata."""
    artifacts = _load_artifacts_for_dataset(dataset_version)
    
    # Try profiling artifacts first
    for artifact in artifacts.get('profiling', []):
        if 'quality' in artifact and 'quality_score' in artifact:
            # Check if this has row count info
            if 'row_count' in artifact:
                return artifact.get('row_count')
    
    # Fallback: try to get from metadata notes or tables_loaded
    # We could query DuckDB but that would be a heavy dependency
    return None


def _extract_quality_metrics(dataset_version: str) -> Tuple[Optional[float], Optional[int], Optional[int]]:
    """Extract quality score, passed, failed from artifacts."""
    artifacts = _load_artifacts_for_dataset(dataset_version)
    
    for artifact in artifacts.get('quality', []):
        if 'summary' in artifact:
            summary = artifact['summary']
            return (
                summary.get('quality_score'),
                summary.get('passed'),
                summary.get('failed')
            )
    
    for artifact in artifacts.get('profiling', []):
        if 'quality' in artifact:
            qual = artifact['quality']
            return (
                qual.get('quality_score'),
                qual.get('checks_passed'),
                qual.get('checks_failed')
            )
    
    return None, None, None


def _extract_schema_diff_metrics(dataset_version: str) -> Optional[Dict[str, Any]]:
    """Extract schema diff metrics from artifacts."""
    artifacts = _load_artifacts_for_dataset(dataset_version)
    
    for artifact in artifacts.get('schema_diff', []):
        if 'missing' in artifact or 'extra' in artifact:
            return {
                'missing_columns': len(artifact.get('missing', [])),
                'extra_columns': len(artifact.get('extra', [])),
                'details': artifact
            }
    return None


def _extract_change_detection_metrics(dataset_version: str) -> Optional[Dict[str, Any]]:
    """Extract change detection metrics from artifacts."""
    artifacts = _load_artifacts_for_dataset(dataset_version)
    
    for artifact in artifacts.get('change_detection', []):
        if 'summary' in artifact:
            return artifact['summary']
    return None


def _get_execution_summary_from_metadata(record: Dict[str, Any]) -> ExecutionSummary:
    """Convert a metadata record to ExecutionSummary."""
    return ExecutionSummary(
        dataset_version=record.get('dataset_version', ''),
        status=record.get('status', 'unknown'),
        download_timestamp=record.get('download_timestamp'),
        execution_time=None,  # Not directly stored in metadata
        file_name=record.get('file_name'),
        file_size=record.get('file_size'),
        sha256_checksum=record.get('sha256_checksum'),
        notes=record.get('notes'),
    )


def get_dataset_summary(
    dataset_version: str, 
    db_path: Optional[Path] = None
) -> Optional[DatasetSummary]:
    """
    Get comprehensive summary for a single dataset version.
    
    Args:
        dataset_version: The dataset version identifier (e.g., 'ia07012026')
        db_path: Optional path to metadata database
        
    Returns:
        DatasetSummary or None if not found
    """
    registry = _get_registry(db_path)
    
    # Get metadata record
    datasets = registry.list()
    record = next((d for d in datasets if d['dataset_version'] == dataset_version), None)
    
    if not record:
        return None
    
    # Get artifacts
    artifacts = _load_artifacts_for_dataset(dataset_version)
    
    # Extract metrics
    quality_score, quality_passed, quality_failed = _extract_quality_metrics(dataset_version)
    schema_changes = _extract_schema_diff_metrics(dataset_version)
    data_changes = _extract_change_detection_metrics(dataset_version)
    
    # Build summary
    summary = DatasetSummary(
        dataset_version=record.get('dataset_version', ''),
        dataset_name=record.get('dataset_name'),
        status=record.get('status'),
        ingestion_date=record.get('download_timestamp'),
        file_name=record.get('file_name'),
        file_size=record.get('file_size'),
        sha256_checksum=record.get('sha256_checksum'),
        source_url=record.get('source_url'),
        notes=record.get('notes'),
        quality_score=quality_score,
        quality_checks_passed=quality_passed,
        quality_checks_failed=quality_failed,
        schema_changes=schema_changes,
        data_changes=data_changes,
        artifacts=[
            {'type': k, 'count': len(v)} for k, v in artifacts.items()
        ],
    )
    
    return summary


def get_all_dataset_summaries(
    db_path: Optional[Path] = None
) -> List[DatasetSummary]:
    """Get summaries for all datasets in registry."""
    registry = _get_registry(db_path)
    datasets = registry.list()
    
    summaries = []
    for record in datasets:
        version = record.get('dataset_version')
        if version:
            ds = get_dataset_summary(version, db_path)
            if ds:
                summaries.append(ds)
    return summaries


def _filter_by_date(
    summaries: List[DatasetSummary],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> List[DatasetSummary]:
    """Filter summaries by ingestion date range."""
    filtered = []
    for s in summaries:
        if not s.ingestion_date:
            continue
        try:
            dt = datetime.fromisoformat(s.ingestion_date)
        except (ValueError, TypeError):
            continue
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                if dt < start_dt:
                    continue
            except ValueError:
                pass
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                # If end_date is just a date (YYYY-MM-DD), include all times that day
                if len(end_date) == 10:
                    end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                if dt > end_dt:
                    continue
            except ValueError:
                pass
        
        filtered.append(s)
    return filtered


def get_daily_summary(
    date: str,  # YYYY-MM-DD
    db_path: Optional[Path] = None
) -> Optional[MonthlySummary]:
    """
    Get daily summary for a specific date.
    Returns MonthlySummary with only that day's data.
    """
    summaries = get_all_dataset_summaries(db_path)
    daily = _filter_by_date(summaries, date, date)
    
    if not daily:
        return None
    
    # Build monthly summary for just this day
    try:
        dt = datetime.fromisoformat(date)
        month_summary = MonthlySummary(year=dt.year, month=dt.month, month_key=dt.strftime('%Y-%m'))
    except ValueError:
        month_summary = MonthlySummary(year=0, month=0, month_key=date)
    
    _populate_monthly_summary(month_summary, daily)
    month_summary.calculate_derived_metrics()
    
    return month_summary


def get_monthly_summary(
    year: int,
    month: int,
    db_path: Optional[Path] = None
) -> MonthlySummary:
    """
    Get aggregated monthly summary.
    
    Args:
        year: Year (e.g., 2026)
        month: Month 1-12
        db_path: Optional path to metadata database
        
    Returns:
        MonthlySummary with aggregated metrics
    """
    # Build date range for the month
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"
    
    summaries = get_all_dataset_summaries(db_path)
    monthly_datasets = _filter_by_date(summaries, start_date, end_date)
    
    month_summary = MonthlySummary(
        year=year,
        month=month,
        month_key=f"{year}-{month:02d}"
    )
    
    _populate_monthly_summary(month_summary, monthly_datasets)
    month_summary.calculate_derived_metrics()
    
    return month_summary


def _populate_monthly_summary(
    month_summary: MonthlySummary,
    datasets: List[DatasetSummary]
) -> None:
    """Populate monthly summary from dataset summaries."""
    execution_durations = []
    quality_scores = []
    latest_dt = None
    latest_dataset = None
    
    for ds in datasets:
        month_summary.total_ingestion_attempts += 1
        
        if ds.status == 'success':
            month_summary.successful_ingestions += 1
        elif ds.status == 'failed':
            month_summary.failed_ingestions += 1
        elif ds.status == 'skipped':
            month_summary.skipped_ingestions += 1
        
        if ds.dataset_version:
            month_summary.datasets_processed.append(ds.dataset_version)
        
        if ds.file_size:
            month_summary.total_file_size_bytes += ds.file_size
        
        if ds.bronze_rows:
            month_summary.total_bronze_rows += ds.bronze_rows
        if ds.silver_rows:
            month_summary.total_silver_rows += ds.silver_rows
        if ds.gold_rows:
            month_summary.total_gold_rows += ds.gold_rows
        
        if ds.quality_score is not None:
            quality_scores.append(ds.quality_score)
        
        # Track latest
        if ds.ingestion_date:
            try:
                dt = datetime.fromisoformat(ds.ingestion_date)
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
                    latest_dataset = ds.dataset_version
            except (ValueError, TypeError):
                pass
    
    month_summary.quality_scores = quality_scores
    month_summary.latest_dataset = latest_dataset
    month_summary.latest_ingestion_date = latest_dt.isoformat() if latest_dt else None
    
    # Count warnings/errors from artifacts (simplified)
    for ds in datasets:
        month_summary.total_warnings += ds.quality_checks_failed or 0


def get_historical_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Path] = None
) -> HistoricalSummary:
    """
    Get aggregated historical summary across date range.
    
    Args:
        start_date: Start date (YYYY-MM-DD), None for all history
        end_date: End date (YYYY-MM-DD), None for up to now
        db_path: Optional path to metadata database
        
    Returns:
        HistoricalSummary with aggregated metrics
    """
    summaries = get_all_dataset_summaries(db_path)
    
    # Apply date filtering
    if start_date or end_date:
        summaries = _filter_by_date(summaries, start_date, end_date)
    
    hist = HistoricalSummary(
        start_date=start_date,
        end_date=end_date
    )
    
    monthly_data = defaultdict(list)
    
    for ds in summaries:
        hist.dataset_versions.append(ds.dataset_version)
        hist.ingestion_dates.append(ds.ingestion_date or '')
        
        if ds.status == 'success':
            hist.successful_datasets += 1
        elif ds.status == 'failed':
            hist.failed_datasets += 1
        
        if ds.file_size:
            hist.total_file_size_bytes += ds.file_size
        
        if ds.quality_score is not None:
            hist.quality_scores.append(ds.quality_score)
        
        # Execution duration not directly available
        # Could try to extract from pipeline metadata but not persisted currently
        
        if ds.schema_changes:
            hist.schema_changes_history.append({
                'dataset_version': ds.dataset_version,
                'changes': ds.schema_changes
            })
        
        if ds.data_changes:
            hist.data_changes_history.append({
                'dataset_version': ds.dataset_version,
                'changes': ds.data_changes
            })
        
        # Group by month
        if ds.ingestion_date:
            try:
                month_key = datetime.fromisoformat(ds.ingestion_date).strftime('%Y-%m')
                monthly_data[month_key].append(ds)
            except (ValueError, TypeError):
                pass
        
        hist.dataset_summaries.append(ds)
    
    # Build monthly summaries
    for month_key in sorted(monthly_data.keys()):
        try:
            year_str, month_str = month_key.split('-')
            year, month = int(year_str), int(month_str)
            ms = MonthlySummary(year=year, month=month, month_key=month_key)
            _populate_monthly_summary(ms, monthly_data[month_key])
            ms.calculate_derived_metrics()
            hist.monthly_summaries.append(ms)
        except (ValueError, IndexError):
            pass
    
    hist.calculate_derived_metrics()
    return hist


def get_execution_summaries(
    db_path: Optional[Path] = None
) -> List[ExecutionSummary]:
    """Get execution summaries from metadata."""
    registry = _get_registry(db_path)
    datasets = registry.list()
    
    return [_get_execution_summary_from_metadata(d) for d in datasets]