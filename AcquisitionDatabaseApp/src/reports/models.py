"""
Structured data models for reporting aggregation.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class ExecutionSummary:
    """Single execution summary from metadata or telemetry."""
    dataset_version: str
    status: str  # 'success', 'failed', 'skipped'
    download_timestamp: Optional[str] = None
    execution_time: Optional[float] = None  # seconds
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    sha256_checksum: Optional[str] = None
    notes: Optional[str] = None
    
    # Optional enriched metrics (None if unavailable)
    bronze_rows: Optional[int] = None
    silver_rows: Optional[int] = None
    gold_rows: Optional[int] = None
    quality_score: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def timestamp_dt(self) -> Optional[datetime]:
        """Parse download_timestamp to datetime."""
        if self.download_timestamp:
            try:
                return datetime.fromisoformat(self.download_timestamp)
            except (ValueError, TypeError):
                return None
        return None
    
    @property
    def month_key(self) -> Optional[str]:
        """Return YYYY-MM key for monthly grouping."""
        dt = self.timestamp_dt
        if dt:
            return dt.strftime('%Y-%m')
        return None
    
    @property
    def date_key(self) -> Optional[str]:
        """Return YYYY-MM-DD key for daily grouping."""
        dt = self.timestamp_dt
        if dt:
            return dt.strftime('%Y-%m-%d')
        return None


@dataclass
class DatasetSummary:
    """Aggregated summary for a single dataset."""
    dataset_version: str
    dataset_name: Optional[str] = None
    status: Optional[str] = None
    ingestion_date: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    sha256_checksum: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None
    
    # Layer metrics
    bronze_rows: Optional[int] = None
    silver_rows: Optional[int] = None
    gold_rows: Optional[int] = None
    
    # Quality metrics
    quality_score: Optional[float] = None
    quality_checks_passed: Optional[int] = None
    quality_checks_failed: Optional[int] = None
    
    # Schema/diff metrics
    schema_changes: Optional[Dict[str, Any]] = None
    data_changes: Optional[Dict[str, Any]] = None
    
    # Execution metrics
    execution_duration: Optional[float] = None
    
    # Artifacts
    artifacts: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'dataset_version': self.dataset_version,
            'dataset_name': self.dataset_name,
            'status': self.status,
            'ingestion_date': self.ingestion_date,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'sha256_checksum': self.sha256_checksum,
            'source_url': self.source_url,
            'notes': self.notes,
            'bronze_rows': self.bronze_rows,
            'silver_rows': self.silver_rows,
            'gold_rows': self.gold_rows,
            'quality_score': self.quality_score,
            'quality_checks_passed': self.quality_checks_passed,
            'quality_checks_failed': self.quality_checks_failed,
            'schema_changes': self.schema_changes,
            'data_changes': self.data_changes,
            'execution_duration': self.execution_duration,
            'artifacts': self.artifacts,
        }


@dataclass
class MonthlySummary:
    """Aggregated monthly operational summary."""
    year: int
    month: int
    month_key: str  # YYYY-MM
    
    # Ingestion counts
    total_ingestion_attempts: int = 0
    successful_ingestions: int = 0
    failed_ingestions: int = 0
    skipped_ingestions: int = 0
    
    # Success metrics
    success_rate: float = 0.0
    
    # Dataset metrics
    datasets_processed: List[str] = field(default_factory=list)
    total_file_size_bytes: int = 0
    total_bronze_rows: int = 0
    total_silver_rows: int = 0
    total_gold_rows: int = 0
    
    # Execution metrics
    avg_execution_duration: Optional[float] = None
    total_execution_time: Optional[float] = None
    
    # Quality metrics
    avg_quality_score: Optional[float] = None
    quality_scores: List[float] = field(default_factory=list)
    
    # Issues
    total_warnings: int = 0
    total_errors: int = 0
    
    # Latest dataset
    latest_dataset: Optional[str] = None
    latest_ingestion_date: Optional[str] = None
    
    # Execution summaries
    executions: List[ExecutionSummary] = field(default_factory=list)
    
    def calculate_derived_metrics(self):
        """Calculate derived metrics from raw data."""
        # Success rate
        if self.total_ingestion_attempts > 0:
            self.success_rate = (self.successful_ingestions / self.total_ingestion_attempts) * 100
        
        # Average execution duration
        durations = [e.execution_time for e in self.executions if e.execution_time is not None]
        if durations:
            self.avg_execution_duration = sum(durations) / len(durations)
            self.total_execution_time = sum(durations)
        
        # Average quality score
        if self.quality_scores:
            self.avg_quality_score = sum(self.quality_scores) / len(self.quality_scores)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'year': self.year,
            'month': self.month,
            'month_key': self.month_key,
            'total_ingestion_attempts': self.total_ingestion_attempts,
            'successful_ingestions': self.successful_ingestions,
            'failed_ingestions': self.failed_ingestions,
            'skipped_ingestions': self.skipped_ingestions,
            'success_rate': self.success_rate,
            'datasets_processed': self.datasets_processed,
            'total_file_size_bytes': self.total_file_size_bytes,
            'total_bronze_rows': self.total_bronze_rows,
            'total_silver_rows': self.total_silver_rows,
            'total_gold_rows': self.total_gold_rows,
            'avg_execution_duration': self.avg_execution_duration,
            'total_execution_time': self.total_execution_time,
            'avg_quality_score': self.avg_quality_score,
            'total_warnings': self.total_warnings,
            'total_errors': self.total_errors,
            'latest_dataset': self.latest_dataset,
            'latest_ingestion_date': self.latest_ingestion_date,
        }


@dataclass
class HistoricalSummary:
    """Aggregated historical operational summary across date range."""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    
    # Dataset metrics
    total_datasets: int = 0
    dataset_versions: List[str] = field(default_factory=list)
    ingestion_dates: List[str] = field(default_factory=list)
    
    # Status metrics
    successful_datasets: int = 0
    failed_datasets: int = 0
    
    # Size metrics
    total_file_size_bytes: int = 0
    avg_file_size_bytes: Optional[float] = None
    
    # Row count metrics
    total_bronze_rows: int = 0
    total_silver_rows: int = 0
    total_gold_rows: int = 0
    
    # Quality metrics
    quality_scores: List[float] = field(default_factory=list)
    avg_quality_score: Optional[float] = None
    
    # Execution metrics
    execution_durations: List[float] = field(default_factory=list)
    avg_execution_duration: Optional[float] = None
    total_execution_time: Optional[float] = None
    
    # Schema/diff metrics
    schema_changes_history: List[Dict[str, Any]] = field(default_factory=list)
    data_changes_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Monthly breakdown
    monthly_summaries: List[MonthlySummary] = field(default_factory=list)
    
    # Dataset summaries
    dataset_summaries: List[DatasetSummary] = field(default_factory=list)
    
    def calculate_derived_metrics(self):
        """Calculate derived metrics from raw data."""
        self.total_datasets = len(self.dataset_versions)
        
        # Average file size
        file_sizes = [ds.file_size for ds in self.dataset_summaries if ds.file_size is not None]
        if file_sizes:
            self.avg_file_size_bytes = sum(file_sizes) / len(file_sizes)
            self.total_file_size_bytes = sum(file_sizes)
        
        # Average quality score
        if self.quality_scores:
            self.avg_quality_score = sum(self.quality_scores) / len(self.quality_scores)
        
        # Average execution duration
        if self.execution_durations:
            self.avg_execution_duration = sum(self.execution_durations) / len(self.execution_durations)
            self.total_execution_time = sum(self.execution_durations)
        
        # Row totals
        for ds in self.dataset_summaries:
            if ds.bronze_rows is not None:
                self.total_bronze_rows += ds.bronze_rows
            if ds.silver_rows is not None:
                self.total_silver_rows += ds.silver_rows
            if ds.gold_rows is not None:
                self.total_gold_rows += ds.gold_rows
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'total_datasets': self.total_datasets,
            'dataset_versions': self.dataset_versions,
            'ingestion_dates': self.ingestion_dates,
            'successful_datasets': self.successful_datasets,
            'failed_datasets': self.failed_datasets,
            'total_file_size_bytes': self.total_file_size_bytes,
            'avg_file_size_bytes': self.avg_file_size_bytes,
            'total_bronze_rows': self.total_bronze_rows,
            'total_silver_rows': self.total_silver_rows,
            'total_gold_rows': self.total_gold_rows,
            'avg_quality_score': self.avg_quality_score,
            'avg_execution_duration': self.avg_execution_duration,
            'total_execution_time': self.total_execution_time,
            'monthly_summaries': [m.to_dict() for m in self.monthly_summaries],
            'dataset_summaries': [d.to_dict() for d in self.dataset_summaries],
        }