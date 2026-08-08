from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import json

@dataclass
class ProfileResult:
    """Base class for all profiling results."""
    profiler_type: str
    table_name: str
    results: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'profiler_type': self.profiler_type,
            'table_name': self.table_name,
            'results': self.results
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

class BaseProfiler(ABC):
    """Base class for all profilers."""
    
    def __init__(self, storage_manager=None):
        from storage import StorageManager
        self.storage = storage_manager or StorageManager()
    
    @abstractmethod
    def profile(self, dataset_version: str, table_name: str, **kwargs) -> ProfileResult:
        """Run profiling and return structured results."""
        pass
    
    def save_results(self, dataset_version: str, table_name: str, results: ProfileResult):
        """Save results to storage."""
        artifact_type = f"profiling/{self.__class__.__name__.lower()}"
        filename = f"{table_name}.json"
        self.storage.save_artifact(
            dataset_version, 
            artifact_type, 
            filename, 
            results.to_json()
        )