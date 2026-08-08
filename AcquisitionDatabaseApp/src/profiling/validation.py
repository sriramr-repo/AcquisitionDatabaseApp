from typing import Dict, Any, List
from .base import BaseProfiler, ProfileResult
from .quality import QualityProfiler


class ValidationReportGenerator(BaseProfiler):
    """Generates validation reports based on quality rules."""
    
    def __init__(self, storage_manager=None):
        super().__init__(storage_manager)
        self.quality_profiler = QualityProfiler(storage_manager)
    
    def profile(self, dataset_version: str, table_name: str, **kwargs) -> ProfileResult:
        quality_result = self.quality_profiler.profile(dataset_version, table_name, **kwargs)
        quality_data = quality_result.results
        
        report = {
            'table_name': table_name,
            'validation_status': 'passed' if quality_data.get('quality_score', 0) >= 70 else 'failed',
            'rules_checked': [],
            'warnings': [],
            'errors': [],
            'summary': {
                'total_rules': 0,
                'passed': 0,
                'failed': 0,
                'warnings': 0
            }
        }
        
        rules = [
            ('null_threshold', self._check_nulls, quality_data.get('column_quality', [])),
            ('quality_score', self._check_quality_score, quality_data.get('quality_score', 0)),
            ('data_presence', self._check_data_presence, quality_data.get('total_rows', 0)),
        ]
        
        for rule_name, rule_fn, target in rules:
            report['summary']['total_rules'] += 1
            passed = rule_fn(target)
            if passed:
                report['summary']['passed'] += 1
                report['rules_checked'].append({'name': rule_name, 'status': 'passed'})
            else:
                report['summary']['failed'] += 1
                report['rules_checked'].append({'name': rule_name, 'status': 'failed'})
                report['errors'].append(f"Rule {rule_name} failed")
        
        return ProfileResult(
            profiler_type='validation',
            table_name=table_name,
            results=report
        )
    
    def _check_nulls(self, column_quality: List[Dict]) -> bool:
        return all(col.get('completeness_percentage', 0) >= 80 for col in column_quality)
    
    def _check_quality_score(self, score: float) -> bool:
        return score >= 70
    
    def _check_data_presence(self, total_rows: int) -> bool:
        return total_rows > 0