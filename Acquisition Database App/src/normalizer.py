import hashlib
import json
from datetime import datetime
from typing import Dict, List, Any
import pandas as pd
from canonical_models import Firm, FirmOffice, FirmAcquiredFirm, OfficeType

class Normalizer:
    """Transforms raw SEC data into Silver-layer canonical entities."""

    def __init__(self, dataset_version: str):
        self.version = dataset_version

    def normalize_batch(self, df: pd.DataFrame) -> Dict[str, List[BaseModel]]:
        """Process a batch of raw records into normalized entities."""
        normalized = {
            "firms": [],
            "offices": [],
            "acquired_firms": []
        }

        for _, row in df.iterrows():
            row_dict = row.to_dict()
            record_hash = self._generate_hash(row_dict)
            
            # 1. Normalize Firm
            firm_data = {**row_dict}
            firm_data.update({
                "dataset_version": self.version,
                "created_timestamp": datetime.utcnow(),
                "source_record_hash": record_hash,
                "current_status_flag": "active"
            })
            firm = Firm(**firm_data)
            normalized["firms"].append(firm)

            # 2. Normalize Offices (Main, Mail, Books&Records)
            normalized["offices"].extend(self._extract_offices(firm.firm_id, row_dict))

            # 3. Normalize Acquired Firms (if present)
            if row_dict.get("Acquired Firm"):
                acquired = FirmAcquiredFirm(
                    parent_firm_id=firm.firm_id,
                    acquired_name=row_dict.get("Acquired Firm"),
                    acquired_sec_number=row_dict.get("Acquired Firm SEC#"),
                    acquired_crd_number=row_dict.get("Acquired Firm CRD#")
                )
                normalized["acquired_firms"].append(acquired)

        return normalized

    def _extract_offices(self, firm_id: str, row: Dict[str, Any]) -> List[FirmOffice]:
        offices = []
        # Mapping patterns for different office types in the flat SEC row
        types = {
            OfficeType.MAIN: "Main Office",
            OfficeType.MAIL: "Mail Office",
            OfficeType.BOOKS_RECORDS: "Location of Books and Records"
        }
        
        for o_type, prefix in types.items():
            addr1 = row.get(f"{prefix} Street Address 1")
            if not addr1: continue
            
            offices.append(FirmOffice(
                firm_id=firm_id,
                office_type=o_type,
                street_address_1=addr1,
                street_address_2=row.get(f"{prefix} Street Address 2"),
                city=row.get(f"{prefix} City"),
                state=row.get(f"{prefix} State"),
                country=row.get(f"{prefix} Country"),
                postal_code=row.get(f"{prefix} Postal Code"),
                is_private_residence=self._parse_bool(row.get(f"{prefix} Private Residence Flag")),
                telephone=row.get(f"{prefix} Telephone Number") if o_type == OfficeType.MAIN else None,
                facsimile=row.get(f"{prefix} Facsimile Number") if o_type == OfficeType.MAIN else None
            ))
        return offices

    def _parse_bool(self, val: Any) -> bool:
        if not val: return False
        return str(val).strip().upper() == 'Y'

    def _generate_hash(self, data: Dict[str, Any]) -> str:
        """Deterministically hash the source record for change detection."""
        content = json.dumps(data, sort_keys=True, default=str).encode('utf-8')
        return hashlib.sha256(content).hexdigest()