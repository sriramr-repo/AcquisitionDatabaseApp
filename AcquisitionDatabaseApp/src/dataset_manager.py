import hashlib
import json
import pathlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

@dataclass
class DatasetFingerprint:
    sha256: str
    row_count: int
    table_count: int
    csv_names: List[str]
    column_counts: Dict[str, int]
    column_names: Dict[str, List[str]]
    version_id: str

    @staticmethod
    def create(csv_paths: List[pathlib.Path], version_id: str):
        col_counts, col_names, total_rows, hasher = {}, {}, 0, hashlib.sha256()
        for p in sorted(csv_paths):
            with open(p, 'rb') as f:
                content = f.read()
                hasher.update(content)
                header = content.splitlines()[0].decode().split(',')
                col_counts[p.name] = len(header)
                col_names[p.name] = header
                total_rows += len(content.splitlines()) - 1
        return DatasetFingerprint(hasher.hexdigest(), total_rows, len(csv_paths), [p.name for p in csv_paths], col_counts, col_names, version_id)

@dataclass
class DatasetVersion:
    id: str
    fingerprint: DatasetFingerprint
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_id: Optional[str] = None
    prev_version_id: Optional[str] = None
    next_version_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)

class DatasetVersionManager:
    def __init__(self):
        self.history: Dict[str, DatasetVersion] = {}
        self.head: Optional[str] = None

    def register(self, fingerprint: DatasetFingerprint, parent_id: Optional[str] = None):
        if fingerprint.version_id in self.history:
            raise ValueError(f"Duplicate version id: {fingerprint.version_id}")
        if parent_id and parent_id not in self.history:
            raise ValueError(f"Unknown parent: {parent_id}")
        new_v = DatasetVersion(id=fingerprint.version_id, fingerprint=fingerprint, parent_id=parent_id, prev_version_id=self.head)
        if self.head:
            self.history[self.head].next_version_id = new_v.id
        if parent_id:
            self.history[parent_id].children_ids.append(new_v.id)
        self.history[new_v.id] = new_v
        self.head = new_v.id

    def compare_versions(self, v1_id: str, v2_id: str):
        v1, v2 = self.history[v1_id].fingerprint, self.history[v2_id].fingerprint
        t1, t2 = set(v1.column_names), set(v2.column_names)
        return {
            "tables": {"missing": t1 - t2, "new": t2 - t1},
            "schema_changes": {
                t: {
                    "added": list(set(v2.column_names[t]) - set(v1.column_names.get(t, []))),
                    "removed": list(set(v1.column_names.get(t, [])) - set(v2.column_names[t]))
                }
                for t in t2 if v1.column_counts.get(t) != v2.column_counts[t]
            }
        }

    def detect_schema_changes(self, v1: str, v2: str): return self.compare_versions(v1, v2)["schema_changes"]
    def detect_missing_tables(self, v1: str, v2: str): return self.compare_versions(v1, v2)["tables"]["missing"]
    def detect_new_tables(self, v1: str, v2: str): return self.compare_versions(v1, v2)["tables"]["new"]
    def detect_column_changes(self, v1: str, v2: str): return self.detect_schema_changes(v1, v2)

    # --- lineage traversal ---
    def get_ancestors(self, version_id: str) -> List[DatasetVersion]:
        res = []
        cur = self.history.get(version_id)
        while cur and cur.parent_id:
            cur = self.history.get(cur.parent_id)
            if cur: res.append(cur)
        return res

    def get_descendants(self, version_id: str) -> List[DatasetVersion]:
        res, stack = [], [version_id]
        while stack:
            cid = stack.pop()
            for child_id in self.history[cid].children_ids:
                child = self.history[child_id]
                res.append(child)
                stack.append(child_id)
        return res

    def get_lineage(self, version_id: str) -> List[DatasetVersion]:
        return self.get_ancestors(version_id) + [self.history[version_id]] + self.get_descendants(version_id)

    # --- persistence ---
    def save(self, path: pathlib.Path):
        data = {v.id: {"fingerprint": asdict(v.fingerprint), "timestamp": v.timestamp.isoformat(), 
                       "parent_id": v.parent_id, "prev_version_id": v.prev_version_id, 
                       "next_version_id": v.next_version_id, "children_ids": v.children_ids}
                for v in self.history.values()}
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: pathlib.Path):
        mgr = cls()
        data = json.loads(path.read_text())
        for vid, vdata in data.items():
            fp = DatasetFingerprint(**vdata["fingerprint"])
            ver = DatasetVersion(
                id=vid, fingerprint=fp,
                timestamp=datetime.fromisoformat(vdata["timestamp"]),
                parent_id=vdata["parent_id"],
                prev_version_id=vdata["prev_version_id"],
                next_version_id=vdata["next_version_id"],
                children_ids=vdata["children_ids"]
            )
            mgr.history[vid] = ver
        if mgr.history:
            mgr.head = max(mgr.history.values(), key=lambda v: v.timestamp).id
        mgr._verify_integrity()
        return mgr

    def _verify_integrity(self):
        for v in self.history.values():
            # structural integrity
            if v.prev_version_id and v.prev_version_id not in self.history:
                raise ValueError(f"Broken prev link: {v.id} -> {v.prev_version_id}")
            if v.next_version_id and v.next_version_id not in self.history:
                raise ValueError(f"Broken next link: {v.id} -> {v.next_version_id}")
            for c in v.children_ids:
                if c not in self.history or self.history[c].parent_id != v.id:
                    raise ValueError(f"Broken child link: {v.id} -> {c}")
