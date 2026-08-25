"""Metadata-first registration of historical Form ADV CSV filings."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from src.research import ResearchRepository


ALIASES = {
    "firm_id": ("organization crd#", "organization crd", "crd", "crd_number", "firm_id"),
    "filing_date": ("latest adv filing date", "filing date", "filing_date", "date"),
    "form_version": ("form version", "form_version", "form"),
}


def _column_map(columns: list[str]) -> dict[str, str]:
    normalized = {str(column).strip().lower(): str(column) for column in columns}
    result: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                result[canonical] = normalized[alias]
                break
    return result


def parse_historical_adv_csv(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    frame = pd.read_csv(path, dtype=str)
    columns = _column_map(list(frame.columns))
    if "firm_id" not in columns:
        raise ValueError("Historical ADV CSV must contain a firm/CRD identifier column")
    frame["firm_id"] = frame[columns["firm_id"]].astype("string").str.strip()
    frame["crd_number"] = frame["firm_id"]
    if "filing_date" in columns:
        frame["filing_date"] = frame[columns["filing_date"]].astype("string").str.strip()
    else:
        frame["filing_date"] = pd.NA
    if "form_version" in columns:
        frame["form_version"] = frame[columns["form_version"]].astype("string").str.strip()
    else:
        frame["form_version"] = pd.NA
    frame["raw_source_path"] = str(path)
    return frame


def register_historical_adv_csv(
    path: Path | str,
    repository: ResearchRepository,
    *,
    source_url: str | None = None,
    content_hash: str | None = None,
) -> int:
    path = Path(path)
    frame = parse_historical_adv_csv(path)
    content_hash = content_hash or hashlib.sha256(path.read_bytes()).hexdigest()
    registered = 0
    for record in frame.to_dict("records"):
        firm_id = str(record["firm_id"]).strip()
        filing_date = record.get("filing_date")
        if not firm_id or pd.isna(filing_date) or not str(filing_date).strip():
            continue
        value = lambda key: None if pd.isna(record.get(key)) else str(record.get(key))
        repository.register_historical_filing(
            firm_id=firm_id,
            crd_number=value("crd_number"),
            filing_date=str(filing_date).strip(),
            form_version=value("form_version"),
            source_url_value=source_url,
            source_path=str(path),
            content_hash=content_hash,
            metadata_json=None,
        )
        registered += 1
    return registered
