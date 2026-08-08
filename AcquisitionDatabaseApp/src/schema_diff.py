import pandas as pd
import json
from typing import Dict
from src.canonical_models import Firm

def check_schema_drift(bronze_cols: list, silver_fields: list = None) -> Dict:
    """Compares bronze columns against canonical Firm model."""
    if silver_fields is None:
        silver_fields = list(Firm.model_fields.keys())
    
    missing = set(silver_fields) - set(bronze_cols)
    extra = set(bronze_cols) - set(silver_fields)
    
    return {"missing": list(missing), "extra": list(extra)}

# ponytail: hardcoded check; move to schema registry if multiple ingestion types exist.
# → skipped: automated SQL type inference, add when schema drift breaks pipeline.