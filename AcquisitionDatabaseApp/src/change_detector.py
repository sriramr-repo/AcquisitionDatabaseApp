"""Step 8: Change detection infrastructure for monthly comparisons."""
import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
from pathlib import Path

from storage import StorageManager, PathResolver
from config import settings


class ChangeDetector:
    """Detects changes between dataset versions for trend analysis."""
    
    def __init__(self, storage: StorageManager = None):
        self.storage = storage or StorageManager()
    
    def compare_versions(self, old_version: str, new_version: str, entity: str = 'firms') -> Dict[str, Any]:
        """Compare two versions of an entity and return change summary."""
        conn = self.storage.get_connection()
        old_table = PathResolver.silver_table(entity, old_version)
        new_table = PathResolver.silver_table(entity, new_version)
        
        # Check tables exist
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        if old_table not in tables or new_table not in tables:
            return {'error': f'Missing tables: {[t for t in [old_table, new_table] if t not in tables]}'}
        
        old_df = conn.execute(f"SELECT * FROM {old_table}").df()
        new_df = conn.execute(f"SELECT * FROM {new_table}").df()
        
        # Determine primary key based on entity
        pk = 'firm_id' if entity == 'firms' else 'firm_id'
        
        old_ids = set(old_df[pk].values)
        new_ids = set(new_df[pk].values)
        
        added = new_ids - old_ids
        removed = old_ids - new_ids
        common = old_ids & new_ids
        
        # Detect modified records
        modified = []
        if common:
            old_common = old_df[old_df[pk].isin(common)].set_index(pk)
            new_common = new_df[new_df[pk].isin(common)].set_index(pk)
            
            for record_id in common:
                old_row = old_common.loc[record_id]
                new_row = new_common.loc[record_id]
                changes = {}
                for col in old_common.columns:
                    old_val = str(old_row[col]) if pd.notna(old_row[col]) else None
                    new_val = str(new_row[col]) if pd.notna(new_row[col]) else None
                    if old_val != new_val:
                        changes[col] = {'old': old_val, 'new': new_val}
                if changes:
                    modified.append({'id': record_id, 'changes': changes})
        
        conn.close()
        
        return {
            'old_version': old_version,
            'new_version': new_version,
            'entity': entity,
            'added': list(added),
            'removed': list(removed),
            'modified': modified,
            'summary': {
                'added_count': len(added),
                'removed_count': len(removed),
                'modified_count': len(modified),
                'unchanged_count': len(common) - len(modified)
            }
        }
    
    def save_change_report(self, version: str, report: Dict[str, Any]) -> Path:
        """Save change detection report to artifacts."""
        filename = f"change_report_{version}_{int(datetime.utcnow().timestamp())}.json"
        self.storage.save_artifact(version, 'change_detection', filename, json.dumps(report, indent=2, default=str))
        return PathResolver.artifact(version, 'change_detection', filename)
    
    def get_version_history(self, entity: str = 'firms') -> List[str]:
        """Get list of available versions for an entity."""
        conn = self.storage.get_connection()
        tables = [t[0] for t in conn.execute("SHOW TABLES").fetchall()]
        conn.close()
        
        prefix = f"silver_{entity}_"
        versions = [t.replace(prefix, '') for t in tables if t.startswith(prefix)]
        return sorted(versions)


# ponytail: simple diff on PK; upgrade to record_hash-based tracking when monthly loads run
# → skipped: SCD Type 2 history table, add when production monthly automation starts
