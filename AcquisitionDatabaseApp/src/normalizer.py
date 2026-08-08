import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
from pydantic import BaseModel
from src.canonical_models import Firm, FirmOffice, FirmAcquiredFirm, OfficeType

class Normalizer:
    def __init__(self, dataset_version: str, mapping_spec_path: str = "data/mapping_specification.json"):
        self.version = dataset_version
        with open(mapping_spec_path, "r") as f:
            self.spec = json.load(f)

    def normalize_batch(self, df: pd.DataFrame) -> Dict[str, List[BaseModel]]:
        normalized = {"firms": [], "offices": [], "acquired_firms": []}
        firm_map = self.spec["entities"]["Firm"]["mappings"]
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            record_hash = self._generate_hash(row_dict)
            firm_data = {target: row_dict.get(source) for target, source in firm_map.items()}
            tracking = {
                "dataset_version": self.version,
                "created_timestamp": datetime.utcnow(),
                "source_dataset": self.version,
                "record_hash": record_hash,
                "last_seen_version": self.version,
                "current_status": "active"
            }
            firm_data.update(tracking)
            try:
                firm = Firm(**firm_data)
                normalized["firms"].append(firm)
                normalized["offices"].extend(self._extract_offices(firm.firm_id, row_dict, tracking))
                if row_dict.get("Acquired Firm"):
                    acquired_data = {
                        "parent_firm_id": firm.firm_id,
                        "acquired_name": row_dict.get("Acquired Firm"),
                        "acquired_sec_number": row_dict.get("Acquired Firm SEC#"),
                        "acquired_crd_number": row_dict.get("Acquired Firm CRD#")
                    }
                    acquired_data.update(tracking)
                    normalized["acquired_firms"].append(FirmAcquiredFirm(**acquired_data))
            except Exception:
                continue
        return normalized

    def _extract_offices(self, firm_id: str, row: Dict[str, Any], tracking: Dict[str, Any]) -> List[FirmOffice]:
        offices = []
        office_spec = self.spec["entities"]["FirmOffice"]
        type_map = {"Main Office": OfficeType.MAIN, "Mail Office": OfficeType.MAIL, "Location of Books and Records": OfficeType.BOOKS_RECORDS}
        for prefix in office_spec["types"]:
            o_type = type_map.get(prefix)
            if not o_type: continue
            addr1 = row.get(f"{prefix} Street Address")
            if not addr1: continue
            office_data = {"firm_id": firm_id, "office_type": o_type}
            for target, suffix in office_spec["common_mappings"].items():
                if target in ["telephone", "facsimile"] and o_type != OfficeType.MAIN: continue
                val = row.get(f"{prefix} {suffix}")
                office_data[target] = self._parse_bool(val) if target == "is_private_residence" else val
            office_data.update(tracking)
            offices.append(FirmOffice(**office_data))
        return offices

    def _parse_bool(self, val: Any) -> bool:
        return str(val).strip().upper() == "Y" if val else False

    def _generate_hash(self, data: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()
