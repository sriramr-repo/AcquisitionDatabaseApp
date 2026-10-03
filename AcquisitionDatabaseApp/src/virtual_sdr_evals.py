"""Deterministic evaluation helpers for Virtual SDR regression datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field

from src.virtual_sdr import SdrBrief, validate_brief_sources


class SdrEvaluationCase(BaseModel):
    case_id: str
    description: str
    brief: SdrBrief
    allowed_source_ids: list[str]
    expected_status: str
    tags: list[str] = Field(default_factory=list)


def load_evaluation_cases(path: Path) -> list[SdrEvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [SdrEvaluationCase.model_validate(item) for item in payload]


def evaluate_case(case: SdrEvaluationCase) -> dict[str, Any]:
    result = validate_brief_sources(case.brief, case.allowed_source_ids)
    return {
        "case_id": case.case_id,
        "actual_status": result.status,
        "expected_status": case.expected_status,
        "passed": result.status == case.expected_status,
        "checks": result.checks,
        "issues": result.issues,
    }


def sync_langsmith_dataset(
    cases: Sequence[SdrEvaluationCase], dataset_name: str = "scm-virtual-sdr-v1"
) -> str:
    """Upload redacted evaluation contracts; no source text or contact PII is included."""
    from langsmith import Client

    client = Client()
    existing = next((item for item in client.list_datasets(dataset_name=dataset_name)), None)
    dataset = existing or client.create_dataset(
        dataset_name=dataset_name,
        description="Citation, completeness, conflict, and safety contracts for SCM Virtual SDR.",
    )
    for case in cases:
        client.create_example(
            dataset_id=dataset.id,
            inputs={
                "case_id": case.case_id,
                "brief": case.brief.model_dump(),
                "allowed_source_ids": case.allowed_source_ids,
            },
            outputs={"expected_status": case.expected_status},
            metadata={"description": case.description, "tags": case.tags},
        )
    return str(dataset.id)
