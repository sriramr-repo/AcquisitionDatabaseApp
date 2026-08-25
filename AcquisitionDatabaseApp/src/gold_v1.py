"""Production materialization for the validated SCM acquisition Gold V1 stack."""

from __future__ import annotations

import os
from pathlib import Path
import duckdb
import pandas as pd

from src.config import settings
from src.gold_priority import evaluate_priorities
from src.gold_priority_readiness import evaluate_priority_readiness
from src.gold_score_aggregator import evaluate_acquisition_scores
from src.storage import PathResolver


GOLD_V1_TABLE_PREFIX = "gold_scm_acquisition_v1_"

# Curated Silver facts retained for research and auditability.  Fields absent
# from an older fixture are added as nulls rather than changing the schema
# order or duplicating scoring logic here.
RESEARCH_COLUMNS = (
    # Firm identity
    "firm_id", "name", "primary_business_name", "sec_number", "cik_number",
    "dataset_version", "source_dataset", "record_hash",
    # Business profile and geography
    "firm_type", "organization_type", "organization_type_other",
    "organization_state", "organization_country", "sec_region",
    "website_address", "sec_current_status", "latest_adv_filing_date",
    "umbrella_registration",
    # AUM, accounts, and client facts
    "total_aum", "discretionary_aum", "non_discretionary_aum",
    "other_regulatory_aum", "total_account_count",
    "discretionary_account_count", "non_discretionary_account_count",
    "individual_client_count", "individual_client_aum",
    "hnw_client_count", "hnw_client_aum", "individual_hnw_client_count",
    "individual_hnw_client_aum", "advises_individuals_or_small_businesses",
    # Staffing, advisory activities, and structure
    "employee_count", "advisory_employee_count", "broker_dealer_rep_count",
    "state_iar_count", "other_adviser_iar_count", "insurance_agent_count",
    "solicitor_count", "provides_financial_planning",
    "provides_pension_consulting", "advises_investment_companies",
    "advises_pooled_investment_vehicles", "advises_institutional_clients",
    "selects_other_advisers", "provides_other_advisory_services",
    "succession_indicator", "succession_date", "has_unlisted_control_person",
    "has_related_person_control", "under_common_control",
    # Item 11 and related regulatory facts
    "disciplinary_event_count", "civil_action_count",
    "bonding_requirement_count", "other_regulatory_event_count",
    "financial_condition_event_count", "affiliation_change_count",
    "has_item_11_disclosure", "has_felony_conviction", "has_felony_charge",
    "has_pending_regulatory_proceeding", "has_pending_civil_proceeding",
)

SCORE_COLUMNS = (
    "score_version", "eligibility_status", "review_required",
    "hard_exclusion_reason", "acquisition_score", "aum_fit_score",
    "discretionary_fit_score", "client_fit_score", "account_practice_fit_score",
    "practice_complexity_score", "advisory_model_fit_score",
    "regulatory_quality_score", "available_component_weight",
    "missing_component_weight", "score_completeness_pct",
    "missing_score_components", "score_completeness_review_flag",
    "regulatory_review_flag",
)

READINESS_COLUMNS = (
    "priority_readiness", "priority_ready", "missing_material_components",
    "priority_readiness_reason_codes", "priority_category",
    "priority_reason_codes",
)

REASON_COLUMNS = (
    "reason_codes", "eligibility_reason_codes", "discretionary_reason_codes",
    "client_fit_reason_codes", "account_practice_reason_codes",
    "practice_complexity_reason_codes", "advisory_model_reason_codes",
    "regulatory_quality_reason_codes",
)

LINEAGE_COLUMNS = (
    "last_seen_version", "current_status", "created_timestamp",
)

GOLD_V1_COLUMNS = tuple(
    dict.fromkeys(
        RESEARCH_COLUMNS
        + REASON_COLUMNS
        + SCORE_COLUMNS
        + READINESS_COLUMNS
        + LINEAGE_COLUMNS
    )
)


def gold_v1_table_name(dataset_version: str) -> str:
    """Return the deterministic DuckDB table name for one dataset version."""
    safe_version = str(dataset_version).replace("-", "")
    return f"{GOLD_V1_TABLE_PREFIX}{safe_version}"


def gold_v1_parquet_path(dataset_version: str) -> Path:
    """Return the deterministic V1 Parquet path."""
    return settings.GOLD_DIR / dataset_version / f"gold_scm_acquisition_v1_{dataset_version}.parquet"


class GoldV1Builder:
    """Orchestrate tested V1 evaluators and materialize only versioned outputs."""

    output_columns = GOLD_V1_COLUMNS

    def build(self, silver_firms: pd.DataFrame) -> pd.DataFrame:
        """Run the existing in-memory scoring stack and impose Gold V1 order."""
        scored = evaluate_acquisition_scores(silver_firms, run_components=True)
        scored = evaluate_priority_readiness(scored)
        scored = evaluate_priorities(scored)
        return self._select_columns(scored)

    def _select_columns(self, scored: pd.DataFrame) -> pd.DataFrame:
        if "firm_id" not in scored.columns:
            raise ValueError("Gold V1 requires firm_id")
        if scored["firm_id"].duplicated().any():
            raise ValueError("Gold V1 requires unique firm_id values")
        result = scored.copy()
        for column in self.output_columns:
            if column not in result.columns:
                result[column] = None
        return result.loc[:, list(self.output_columns)].reset_index(drop=True)

    def write_duckdb(self, frame: pd.DataFrame, connection: duckdb.DuckDBPyConnection, table_name: str) -> None:
        """Write only the deterministic V1 table name, replacing that table."""
        self._validate_frame(frame)
        connection.register("_gold_v1_frame", frame)
        try:
            connection.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM _gold_v1_frame')
        finally:
            connection.unregister("_gold_v1_frame")

    def write_parquet(self, frame: pd.DataFrame, path: Path) -> None:
        """Write Parquet through a same-directory temporary file and replace atomically."""
        self._validate_frame(frame)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        if temporary.exists():
            temporary.unlink()
        local = duckdb.connect()
        try:
            local.register("_gold_v1_frame", frame)
            local.execute(
                "COPY (SELECT * FROM _gold_v1_frame) TO ? (FORMAT PARQUET)",
                [str(temporary)],
            )
            local.unregister("_gold_v1_frame")
        finally:
            local.close()
        os.replace(temporary, path)

    def materialize(
        self,
        silver_firms: pd.DataFrame,
        *,
        connection: duckdb.DuckDBPyConnection,
        dataset_version: str,
        parquet_path: Path | None = None,
    ) -> tuple[pd.DataFrame, str, Path]:
        """Build and write the V1 table plus matching Parquet output."""
        frame = self.build(silver_firms)
        table_name = gold_v1_table_name(dataset_version)
        output_path = parquet_path or gold_v1_parquet_path(dataset_version)
        self.write_duckdb(frame, connection, table_name)
        self.write_parquet(frame, output_path)
        return frame, table_name, Path(output_path)

    @staticmethod
    def _validate_frame(frame: pd.DataFrame) -> None:
        if list(frame.columns) != list(GOLD_V1_COLUMNS):
            raise ValueError("Gold V1 columns do not match the deterministic schema")
        if frame["firm_id"].duplicated().any():
            raise ValueError("Gold V1 requires unique firm_id values")


def load_silver(connection: duckdb.DuckDBPyConnection, dataset_version: str) -> pd.DataFrame:
    """Load the canonical Silver firms table for a dataset version."""
    table = PathResolver.silver_table("firms", dataset_version)
    return connection.execute(f'SELECT * FROM "{table}"').fetchdf()


def materialize_dataset(
    dataset_version: str,
    *,
    connection: duckdb.DuckDBPyConnection | None = None,
    parquet_path: Path | None = None,
) -> tuple[pd.DataFrame, str, Path]:
    """Materialize one Silver dataset into versioned Gold V1 outputs."""
    owns_connection = connection is None
    connection = connection or duckdb.connect(str(settings.DUCKDB_FILE))
    try:
        silver = load_silver(connection, dataset_version)
        return GoldV1Builder().materialize(
            silver,
            connection=connection,
            dataset_version=dataset_version,
            parquet_path=parquet_path,
        )
    finally:
        if owns_connection:
            connection.close()
