"""Client-ready research-list exports sourced from Gold Acquisition V1."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from src.config import settings
from src.gold_v1 import gold_v1_table_name


EXPORT_SCHEMA_VERSION = "SCM_TARGET_EXPORT_V1"

IDENTITY_COLUMNS = (
    "firm_id", "primary_business_name", "name", "sec_number", "website_address",
)
GEOGRAPHY_COLUMNS = ("city", "state", "sec_region")
ECONOMIC_COLUMNS = (
    "total_aum", "discretionary_aum", "discretionary_share",
    "total_account_count", "average_account_size", "individual_hnw_client_aum",
    "individual_hnw_share",
)
STRUCTURE_COLUMNS = ("employee_count", "advisory_employee_count", "organization_type")
BUSINESS_MODEL_COLUMNS = (
    "advises_individuals_or_small_businesses", "provides_financial_planning",
    "advises_pooled_investment_vehicles", "advises_institutional_clients",
)
SCORING_COLUMNS = (
    "acquisition_score", "aum_fit_score", "discretionary_fit_score",
    "client_fit_score", "account_practice_fit_score", "practice_complexity_score",
    "advisory_model_fit_score", "regulatory_quality_score",
)
REVIEW_COLUMNS = (
    "priority_category", "priority_readiness", "review_required",
    "regulatory_review_flag", "score_completeness_pct", "missing_score_components",
)
EXPLAINABILITY_COLUMNS = ("reason_codes", "priority_reason_codes")
RESEARCH_PLACEHOLDERS = (
    "research_status", "founder_name", "founder_estimated_age", "founder_tenure",
    "ownership_notes", "succession_notes", "investment_philosophy_notes", "custodian",
    "strategic_fit_notes", "outreach_recommendation", "analyst_notes",
)

EXPORT_COLUMNS = (
    IDENTITY_COLUMNS
    + GEOGRAPHY_COLUMNS
    + ECONOMIC_COLUMNS
    + STRUCTURE_COLUMNS
    + BUSINESS_MODEL_COLUMNS
    + SCORING_COLUMNS
    + REVIEW_COLUMNS
    + EXPLAINABILITY_COLUMNS
    + ("screening_summary",)
    + RESEARCH_PLACEHOLDERS
)


def _json_codes(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _percent(value: Any) -> str | None:
    number = _number(value)
    return None if number is None else f"{number * 100:.0f}%"


def _money(value: Any) -> str | None:
    number = _number(value)
    if number is None:
        return None
    absolute = abs(number)
    if absolute >= 1_000_000_000:
        return f"${number / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"${number / 1_000:.1f}K"
    return f"${number:,.0f}"


def _count(value: Any) -> str | None:
    number = _number(value)
    return None if number is None else f"{number:g}"


def _is_true(value: Any) -> bool:
    try:
        return bool(value) is True
    except (TypeError, ValueError):
        return False


def _is_false(value: Any) -> bool:
    if value is None:
        return False
    try:
        return bool(value) is False
    except (TypeError, ValueError):
        return False


def _screening_summary(row: pd.Series) -> str:
    parts: list[str] = []
    if (value := _money(row.get("total_aum"))) is not None:
        parts.append(f"{value} AUM")
    if (value := _percent(row.get("discretionary_share"))) is not None:
        parts.append(f"{value} discretionary")
    if (value := _percent(row.get("individual_hnw_share"))) is not None:
        parts.append(f"{value} individual/HNW AUM")
    if (value := _count(row.get("employee_count"))) is not None:
        parts.append(f"{value} employees")
    if (value := _count(row.get("advisory_employee_count"))) is not None:
        parts.append(f"{value} advisory employees")
    if _is_true(row.get("provides_financial_planning")):
        parts.append("financial-planning model")
    if _is_false(row.get("has_item_11_disclosure")):
        parts.append("no Item 11 disclosure")
    if (value := _number(row.get("acquisition_score"))) is not None:
        parts.append(f"acquisition score {value:.1f}")
    return "; ".join(parts) + "." if parts else ""


REVIEW_LABELS = {
    "MISSING_MATERIAL_CLIENT_DATA": "Missing client-mix data",
    "MISSING_MATERIAL_DATA": "Missing material data",
    "INSUFFICIENT_PRIORITY_COMPLETENESS": "Insufficient priority completeness",
    "REGULATORY_REVIEW_REQUIRED": "Regulatory review required",
    "REGISTRATION_REVIEW_REQUIRED": "Ambiguous registration status",
    "AMBIGUOUS_REGISTRATION_STATUS": "Ambiguous registration status",
    "INCOMPLETE_SCORE_REVIEW": "Incomplete score data",
    "INVALID_MATERIAL_SCORING_DATA": "Invalid material scoring data",
}


def _review_reason_summary(row: pd.Series) -> str:
    codes: list[str] = []
    if bool(row.get("regulatory_review_flag", False)):
        codes.append("REGULATORY_REVIEW_REQUIRED")
    for column in ("priority_readiness_reason_codes", "reason_codes"):
        for code in _json_codes(row.get(column)):
            if code not in codes:
                codes.append(code)
    labels = [REVIEW_LABELS[code] for code in codes if code in REVIEW_LABELS]
    return "; ".join(dict.fromkeys(labels)) or "Review required"


def _derive_research_fields(source: pd.DataFrame) -> pd.DataFrame:
    result = source.copy()
    total_aum = pd.to_numeric(result.get("total_aum"), errors="coerce")
    discretionary_aum = pd.to_numeric(result.get("discretionary_aum"), errors="coerce")
    individual_hnw_aum = pd.to_numeric(result.get("individual_hnw_client_aum"), errors="coerce")
    accounts = pd.to_numeric(result.get("total_account_count"), errors="coerce")
    result["discretionary_share"] = (discretionary_aum / total_aum).where(total_aum > 0)
    result["average_account_size"] = (total_aum / accounts).where(accounts > 0)
    result["individual_hnw_share"] = (individual_hnw_aum / total_aum).where(total_aum > 0)
    result["city"] = None
    result["state"] = result.get("organization_state")
    result["screening_summary"] = result.apply(_screening_summary, axis=1)
    return result


def _prepare(source: pd.DataFrame) -> pd.DataFrame:
    if "firm_id" not in source.columns:
        raise ValueError("Target export requires firm_id")
    if source["firm_id"].duplicated().any():
        raise ValueError("Target export requires unique firm_id values")
    result = _derive_research_fields(source)
    for column in EXPORT_COLUMNS:
        if column not in result.columns:
            result[column] = "" if column in RESEARCH_PLACEHOLDERS else None
    return result.loc[:, list(EXPORT_COLUMNS)]


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def export_priority_targets(
    dataset_version: str,
    output_dir: Path | None = None,
    *,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Path]:
    """Export Priority A, Priority B, and the B review queue from Gold V1."""
    owns_connection = connection is None
    connection = connection or duckdb.connect(str(settings.DUCKDB_FILE), read_only=True)
    try:
        table = gold_v1_table_name(dataset_version)
        source = connection.execute(f'SELECT * FROM "{table}"').fetchdf()
    finally:
        if owns_connection:
            connection.close()

    prepared = _prepare(source)
    priority_a = prepared[prepared["priority_category"] == "PRIORITY_A"].copy()
    priority_b = prepared[prepared["priority_category"] == "PRIORITY_B"].copy()
    priority_b_review = priority_b[priority_b["review_required"] == True].copy()  # noqa: E712
    source_by_id = source.set_index("firm_id")
    priority_b_review["review_reason_summary"] = priority_b_review["firm_id"].map(
        source_by_id.apply(_review_reason_summary, axis=1)
    )

    priority_a = priority_a.sort_values(
        ["acquisition_score", "total_aum", "firm_id"],
        ascending=[False, True, True], kind="mergesort",
    )
    priority_b = priority_b.sort_values(
        ["review_required", "acquisition_score", "firm_id"],
        ascending=[True, False, True], kind="mergesort",
    )
    priority_b_review = priority_b_review.sort_values(
        ["acquisition_score", "firm_id"], ascending=[False, True], kind="mergesort"
    )

    root = Path(output_dir) if output_dir is not None else settings.EXPORTS_DIR / "targets" / dataset_version
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "priority_a_csv": root / "priority_a_targets.csv",
        "priority_b_csv": root / "priority_b_targets.csv",
        "priority_b_review_csv": root / "priority_b_review_queue.csv",
        "manifest": root / "target_export_manifest.json",
    }
    _atomic_csv(priority_a, paths["priority_a_csv"])
    _atomic_csv(priority_b, paths["priority_b_csv"])
    _atomic_csv(priority_b_review, paths["priority_b_review_csv"])

    manifest = {
        "dataset_version": dataset_version,
        "score_version": str(source["score_version"].dropna().iloc[0]) if source["score_version"].notna().any() else None,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "gold_v1_source_table": table,
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "priority_a_count": len(priority_a),
        "priority_b_count": len(priority_b),
        "priority_b_review_count": len(priority_b_review),
        "output_filenames": {key: path.name for key, path in paths.items()},
        "city_limitation": "Gold V1 does not contain a canonical city field; city is exported blank.",
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2) + "\n")
    return paths
