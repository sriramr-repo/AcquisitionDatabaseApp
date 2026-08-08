import sqlite3
from typing import Dict, Any, List
from .base import BaseProfiler, ProfileResult
from .schema import SchemaProfiler
from .quality import QualityProfiler
from .dictionary import DataDictionaryGenerator
from .validation import ValidationReportGenerator


class DatasetProfiler:
    """Orchestrates multiple profilers for a dataset."""
    
    def __init__(self, storage_manager=None):
        from storage import StorageManager
        self.storage = storage_manager or StorageManager()
        self.schema_profiler = SchemaProfiler(self.storage)
        self.quality_profiler = QualityProfiler(self.storage)
        self.dictionary_generator = DataDictionaryGenerator(self.storage)
        self.validation_generator = ValidationReportGenerator(self.storage)
    
    def profile_dataset(self, dataset_version: str, table_name: str) -> Dict[str, Any]:
        """Run all profilers on a single table."""
        profile_results = {}
        
        # Run all profilers
        profilers = [
            ('schema', self.schema_profiler),
            ('quality', self.quality_profiler),
            ('dictionary', self.dictionary_generator),
            ('validation', self.validation_generator)
        ]
        
        for name, profiler in profilers:
            result = profiler.profile(dataset_version, table_name)
            profiler.save_results(dataset_version, table_name, result)
            profile_results[name] = result.to_dict()
        
        return {
            'dataset_version': dataset_version,
            'table_name': table_name,
            'profiles': profile_results
        }
    
    def profile_all_tables(self, dataset_version: str) -> Dict[str, Any]:
        """Run profiling on all tables in a dataset version."""
        conn = self.storage.get_connection()
        # Table naming convention: bronze_raw_{table}_{version}
        version_pattern = f"bronze_raw_%{dataset_version.replace('-', '')}"
        tables = [t[0] for t in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_name LIKE ?",
            [version_pattern]
        ).fetchall()]
        conn.close()
        
        all_results = {}
        for table in tables:
            all_results[table] = self.profile_dataset(dataset_version, table)
        
        return {
            'dataset_version': dataset_version,
            'tables_profiled': len(all_results),
            'results': all_results
        }


class ProfileService:
    """Service interface for profiling operations."""
    
    def __init__(self, storage_manager=None):
        from storage import StorageManager
        self.storage = storage_manager or StorageManager()
        self.dataset_profiler = DatasetProfiler(self.storage)
    
    def profile_table(self, dataset_version: str, table_name: str) -> Dict[str, Any]:
        """Profile a specific table."""
        return self.dataset_profiler.profile_dataset(dataset_version, table_name)
    
    def profile_dataset_version(self, dataset_version: str) -> Dict[str, Any]:
        """Profile all tables in a dataset version."""
        return self.dataset_profiler.profile_all_tables(dataset_version)
    
    def get_profile_summary(self, dataset_version: str) -> Dict[str, Any]:
        """Get summary of profiling results for a dataset."""
        # Query saved artifacts
        with self.storage.registry._connect() as conn:
            conn.row_factory = sqlite3.Row
            artifacts = [dict(r) for r in conn.execute(
                "SELECT * FROM artifacts WHERE dataset_version = ? AND artifact_type LIKE 'profiling/%'",
                (dataset_version,)
            )]
        
        return {
            'dataset_version': dataset_version,
            'artifacts_count': len(artifacts),
            'artifact_types': set(a['artifact_type'] for a in artifacts)
        }