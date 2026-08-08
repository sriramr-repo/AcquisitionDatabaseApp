from typing import Dict, Any
from .base import BaseProfiler, ProfileResult
from .schema import SchemaProfiler


class DataDictionaryGenerator(BaseProfiler):
    """Generates data dictionary from schema profiling results."""
    
    def __init__(self, storage_manager=None):
        super().__init__(storage_manager)
        self.schema_profiler = SchemaProfiler(storage_manager)
    
    def profile(self, dataset_version: str, table_name: str, **kwargs) -> ProfileResult:
        schema_result = self.schema_profiler.profile(dataset_version, table_name, **kwargs)
        schema_data = schema_result.results
        
        dictionary = {
            'table_name': table_name,
            'description': self._generate_table_description(table_name, schema_data),
            'fields': []
        }
        
        for col in schema_data.get('columns', []):
            dictionary['fields'].append({
                'name': col['name'],
                'type': col['type'],
                'description': self._generate_field_description(col),
                'nullable': col['nullable'],
                'pattern': col.get('pattern'),
                'sample_values': col.get('sample_values', []),
                'constraints': self._infer_constraints(col)
            })
        
        return ProfileResult(
            profiler_type='dictionary',
            table_name=table_name,
            results=dictionary
        )
    
    def _generate_table_description(self, table_name: str, schema_data: Dict) -> str:
        return f"Table {table_name} containing {schema_data.get('row_count', 0)} records with {schema_data.get('column_count', 0)} fields"
    
    def _generate_field_description(self, col: Dict) -> str:
        desc = f"{col['name']} ({col['type']})"
        if col['nullable']:
            desc += " - nullable"
        return desc
    
    def _infer_constraints(self, col: Dict) -> list:
        constraints = []
        if col['null_percentage'] == 100:
            constraints.append('all_null')
        elif col['null_percentage'] > 50:
            constraints.append('mostly_null')
        if col.get('pattern'):
            constraints.append(f"pattern:{col['pattern']}")
        return constraints