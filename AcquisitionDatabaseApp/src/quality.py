import json
import logging
from typing import Dict, Any, List
from datetime import datetime
from src.storage import StorageManager, PathResolver

logger = logging.getLogger(__name__)

class DataQualityValidator:
    """Validate silver layer data quality."""
    
    def __init__(self, dataset_version: str, storage: StorageManager = None):
        self.version = dataset_version
        self.storage = storage or StorageManager()
        self.report = {
            'dataset_version': dataset_version,
            'validation_timestamp': datetime.utcnow().isoformat(),
            'checks': {},
            'summary': {'total_checks': 0, 'passed': 0, 'failed': 0}
        }
    
    def validate(self) -> Dict[str, Any]:
        """Run all validation checks."""
        checks = [
            self.check_missing_primary_keys,
            self.check_duplicate_firms,
            self.check_duplicate_offices,
            self.check_broken_relationships,
            self.check_orphan_records,
            self.check_unexpected_nulls,
            self.check_normalization_validation
        ]
        
        for check_fn in checks:
            try:
                result = check_fn()
                self.report['checks'][check_fn.__name__] = result
                self.report['summary']['total_checks'] += 1
                if result.get('passed', False):
                    self.report['summary']['passed'] += 1
                else:
                    self.report['summary']['failed'] += 1
            except Exception as e:
                logger.error(f"Check {check_fn.__name__} failed: {e}")
                self.report['checks'][check_fn.__name__] = {
                    'passed': False,
                    'error': str(e)
                }
                self.report['summary']['total_checks'] += 1
                self.report['summary']['failed'] += 1
        
        # Save report
        self.save_report()
        return self.report
    
    def check_missing_primary_keys(self) -> Dict[str, Any]:
        """Check for missing primary keys in silver tables."""
        conn = self.storage.get_connection()
        issues = []
        
        # Check firms
        firm_table = PathResolver.silver_table('firms', self.version)
        result = conn.execute(f"SELECT COUNT(*) FROM {firm_table} WHERE firm_id IS NULL").fetchone()
        if result[0] > 0:
            issues.append(f"{result[0]} firms with NULL firm_id")
        
        # Check offices
        office_table = PathResolver.silver_table('firm_offices', self.version)
        result = conn.execute(f"SELECT COUNT(*) FROM {office_table} WHERE firm_id IS NULL").fetchone()
        if result[0] > 0:
            issues.append(f"{result[0]} offices with NULL firm_id")
        
        # Check acquired firms
        acquired_table = PathResolver.silver_table('firm_acquired_firms', self.version)
        result = conn.execute(f"SELECT COUNT(*) FROM {acquired_table} WHERE parent_firm_id IS NULL").fetchone()
        if result[0] > 0:
            issues.append(f"{result[0]} acquired firms with NULL parent_firm_id")
        
        conn.close()
        passed = len(issues) == 0
        return {'passed': passed, 'issues': issues if not passed else []}
    
    def check_duplicate_firms(self) -> Dict[str, Any]:
        """Check for duplicate firms."""
        conn = self.storage.get_connection()
        table = PathResolver.silver_table('firms', self.version)
        
        # Check for duplicate firm_id
        result = conn.execute(f"""
            SELECT firm_id, COUNT(*) as cnt 
            FROM {table} 
            GROUP BY firm_id 
            HAVING COUNT(*) > 1
        """).fetchall()
        
        issues = []
        for row in result:
            issues.append(f"Duplicate firm_id: {row[0]} ({row[1]} occurrences)")
        
        conn.close()
        passed = len(issues) == 0
        return {'passed': passed, 'issues': issues if not passed else []}
    
    def check_duplicate_offices(self) -> Dict[str, Any]:
        """Check for duplicate offices."""
        conn = self.storage.get_connection()
        table = PathResolver.silver_table('firm_offices', self.version)
        
        # Check for duplicate (firm_id, office_type)
        result = conn.execute(f"""
            SELECT firm_id, office_type, COUNT(*) as cnt 
            FROM {table} 
            GROUP BY firm_id, office_type 
            HAVING COUNT(*) > 1
        """).fetchall()
        
        issues = []
        for row in result:
            issues.append(f"Duplicate office for firm {row[0]} type {row[1]}: {row[2]} occurrences")
        
        conn.close()
        passed = len(issues) == 0
        return {'passed': passed, 'issues': issues if not passed else []}
    
    def check_broken_relationships(self) -> Dict[str, Any]:
        """Check for broken relationships between tables."""
        conn = self.storage.get_connection()
        issues = []
        
        firm_table = PathResolver.silver_table('firms', self.version)
        office_table = PathResolver.silver_table('firm_offices', self.version)
        acquired_table = PathResolver.silver_table('firm_acquired_firms', self.version)
        
        # Check offices referencing non-existent firms
        result = conn.execute(f"""
            SELECT COUNT(*) 
            FROM {office_table} o
            LEFT JOIN {firm_table} f ON o.firm_id = f.firm_id
            WHERE f.firm_id IS NULL
        """).fetchone()
        if result[0] > 0:
            issues.append(f"{result[0]} offices reference non-existent firms")
        
        # Check acquired firms referencing non-existent parent firms
        result = conn.execute(f"""
            SELECT COUNT(*) 
            FROM {acquired_table} a
            LEFT JOIN {firm_table} f ON a.parent_firm_id = f.firm_id
            WHERE f.firm_id IS NULL
        """).fetchone()
        if result[0] > 0:
            issues.append(f"{result[0]} acquired firms reference non-existent parent firms")
        
        conn.close()
        passed = len(issues) == 0
        return {'passed': passed, 'issues': issues if not passed else []}
    
    def check_orphan_records(self) -> Dict[str, Any]:
        """Check for orphan records (firms without offices)."""
        conn = self.storage.get_connection()
        issues = []
        
        firm_table = PathResolver.silver_table('firms', self.version)
        office_table = PathResolver.silver_table('firm_offices', self.version)
        
        # Check firms without any offices
        result = conn.execute(f"""
            SELECT COUNT(*) 
            FROM {firm_table} f
            LEFT JOIN {office_table} o ON f.firm_id = o.firm_id
            WHERE o.firm_id IS NULL
        """).fetchone()
        if result[0] > 0:
            issues.append(f"{result[0]} firms have no offices")
        
        conn.close()
        passed = len(issues) == 0
        return {'passed': passed, 'issues': issues if not passed else [], 'severity': 'warning'}
    
    def check_invalid_foreign_keys(self) -> Dict[str, Any]:
        """Check for invalid foreign keys (using check_broken_relationships)."""
        # Reuse broken_relationships check
        return self.check_broken_relationships()
    
    def check_unexpected_nulls(self) -> Dict[str, Any]:
        """Check for unexpected null values in critical fields."""
        conn = self.storage.get_connection()
        issues = []
        
        firm_table = PathResolver.silver_table('firms', self.version)
        office_table = PathResolver.silver_table('firm_offices', self.version)
        
        # Check critical firm fields
        critical_firm_fields = ['name', 'firm_type', 'sec_current_status']
        for field in critical_firm_fields:
            result = conn.execute(f"SELECT COUNT(*) FROM {firm_table} WHERE {field} IS NULL").fetchone()
            if result[0] > 0:
                issues.append(f"{result[0]} firms with NULL {field}")
        
        # Check critical office fields (Main Office only)
        critical_office_fields = ['street_address_1', 'city', 'state']
        for field in critical_office_fields:
            result = conn.execute(f"""
                SELECT COUNT(*) FROM {office_table} 
                WHERE {field} IS NULL AND office_type = 'MAIN'
            """).fetchone()
            if result[0] > 0:
                issues.append(f"{result[0]} MAIN offices with NULL {field}")
        
        conn.close()
        passed = len(issues) == 0
        return {'passed': passed, 'issues': issues if not passed else []}
    
    def check_normalization_validation(self) -> Dict[str, Any]:
        """Validate normalization: bronze firm row count == silver firms count."""
        conn = self.storage.get_connection()
        issues = []

        # Find bronze table containing firm roster
        tables = [t[0] for t in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'bronze_raw_%'"
        ).fetchall()]
        roster_table = next((t for t in tables if 'firm_roster' in t.lower() or 'ia_sec' in t.lower()), None)

        if roster_table is None:
            conn.close()
            return {'passed': False, 'issues': ['No firm roster bronze table found']}

        bronze_count = conn.execute(f"SELECT COUNT(*) FROM {roster_table}").fetchone()[0]
        silver_count = conn.execute(
            f"SELECT COUNT(*) FROM {PathResolver.silver_table('firms', self.version)}"
        ).fetchone()[0]

        if bronze_count != silver_count:
            issues.append(
                f"Row count mismatch: bronze={bronze_count} silver={silver_count}"
            )

        conn.close()
        return {'passed': len(issues) == 0, 'issues': issues}
    
    def save_report(self):
        """Save validation report to artifact storage."""
        filename = f"quality_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        self.storage.save_artifact(
            self.version,
            'quality',
            filename,
            json.dumps(self.report, indent=2, default=str)
        )
        logger.info(f"Quality report saved: {filename}")


def run_quality_validation(dataset_version: str) -> Dict[str, Any]:
    """Run quality validation for a dataset."""
    validator = DataQualityValidator(dataset_version)
    report = validator.validate()
    
    # Log summary
    summary = report['summary']
    logger.info(f"Quality validation: {summary['passed']}/{summary['total_checks']} checks passed")
    if summary['failed'] > 0:
        logger.warning(f"{summary['failed']} quality checks failed")
    
    return report
