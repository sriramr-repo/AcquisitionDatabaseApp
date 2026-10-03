import duckdb
import pandas as pd
from typing import List, Optional
from src.canonical_models import Firm, FirmOffice, FirmAcquiredFirm

class BaseRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def _save(self, table: str, entities: List):
        if not entities: return
        df = pd.DataFrame([e.model_dump() for e in entities])
        # ponytail: assuming schema matches model exactly. Upgrade if schema evolution needed.
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM df WHERE 1=0")
        self.conn.register("tmp_v", df)
        self.conn.execute(f"INSERT INTO {table} SELECT * FROM tmp_v")
        self.conn.unregister("tmp_v")

class FirmRepository(BaseRepository):
    def save_firms(self, firms: List[Firm]):
        self._save("silver_firms", firms)

    def get_by_id(self, firm_id: str) -> Optional[Firm]:
        res = self.conn.execute("SELECT * FROM silver_firms WHERE firm_id = ?", [firm_id]).df()
        return Firm(**res.iloc[0].to_dict()) if not res.empty else None

class OfficeRepository(BaseRepository):
    def save_offices(self, offices: List[FirmOffice]):
        self._save("silver_offices", offices)

    def get_by_firm(self, firm_id: str) -> List[FirmOffice]:
        res = self.conn.execute("SELECT * FROM silver_offices WHERE firm_id = ?", [firm_id]).df()
        return [FirmOffice(**row) for _, row in res.iterrows()]

class AcquiredFirmRepository(BaseRepository):
    def save_acquired_firms(self, acquired: List[FirmAcquiredFirm]):
        self._save("silver_acquired_firms", acquired)
