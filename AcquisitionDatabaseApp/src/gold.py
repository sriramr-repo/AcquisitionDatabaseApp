import pandas as pd
from pathlib import Path
from typing import Dict
from src.config import settings
from src.storage import StorageManager, PathResolver

class GoldBuilder:
    """Computes acquisition scores and builds Gold layer."""
    
    def __init__(self, storage: StorageManager = None):
        self.storage = storage or StorageManager()

    def build_gold(self, version: str) -> pd.DataFrame:
        conn = self.storage.get_connection()
        firm_table = PathResolver.silver_table('firms', version)
        
        # Read silver firms
        firms = conn.execute(f"SELECT * FROM {firm_table}").df()
        
        # Scoring logic
        firms["score_aum"] = (firms["total_aum"].fillna(0) / 1e9).clip(0, 50)
        firms["score_growth"] = firms["private_fund_count"].fillna(0).clip(0, 20)
        firms["score_risk"] = firms["disciplinary_event_count"].fillna(0) * -5
        
        firms["acquisition_score"] = (
            firms["score_aum"] + 
            firms["score_growth"] + 
            firms["score_risk"]
        ).rank(pct=True)

        # PCA scoring fallback
        if firms["acquisition_score"].std() < 0.01 and len(firms) > 10:
            try:
                from sklearn.decomposition import PCA
                features = ["score_aum", "score_growth", "score_risk"]
                pca = PCA(n_components=1)
                firms["acquisition_score"] = pca.fit_transform(firms[features].fillna(0))
                firms["acquisition_score"] = firms["acquisition_score"].rank(pct=True)
            except ImportError:
                pass

        # Save to Gold Parquet
        output_path = settings.GOLD_DIR / version / f"gold_firms_{version}.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        firms.to_parquet(output_path)
        
        # Save to Gold Table in DuckDB
        gold_table = f"gold_firms_{version.replace('-', '')}"
        conn.register("df_gold", firms)
        conn.execute(f"CREATE OR REPLACE TABLE {gold_table} AS SELECT * FROM df_gold")
        conn.unregister("df_gold")
        
        conn.close()
        return firms
