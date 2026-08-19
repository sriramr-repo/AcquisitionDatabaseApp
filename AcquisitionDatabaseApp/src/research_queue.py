"""Event-driven research refresh queue generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from src.config import settings
from src.gold_v1 import gold_v1_table_name
from src.research import ResearchRepository


REFRESH_EVENTS = {"NEW_PRIORITY_A", "PRIORITY_B_TO_A", "NEW_REGULATORY_DISCLOSURE",
                  "PRIORITY_CHANGE_REVIEW", "ENTERED_TARGET_AUM_BAND"}


def build_research_refresh_queue(dataset_version: str, *, previous_version: str | None = None,
                                 change_report: dict | None = None,
                                 stale_days: int = 180,
                                 research_repository: ResearchRepository | None = None) -> list[dict]:
    repository = research_repository or ResearchRepository()
    connection = duckdb.connect(str(settings.DUCKDB_FILE), read_only=True)
    try:
        table = gold_v1_table_name(dataset_version)
        rows = connection.execute(f'''SELECT firm_id,name,priority_category,acquisition_score
                                      FROM "{table}" WHERE priority_category IN ('PRIORITY_A','PRIORITY_B')''').fetchall()
    finally:
        connection.close()
    events_by_id: dict[str, list[str]] = {}
    for event in (change_report or {}).get("events", []):
        events_by_id.setdefault(str(event["firm_id"]), []).append(event["event_type"])
    now = datetime.now(timezone.utc)
    queue = []
    for firm_id, name, priority, score in rows:
        record = repository.get_research_record(str(firm_id), dataset_version)
        if record is None:
            action = "NEW_TARGET_RESEARCH" if priority == "PRIORITY_A" else "NO_REFRESH_REQUIRED"
            reason = ["missing research record"]
        else:
            reasons = events_by_id.get(str(firm_id), [])
            last = record.get("last_researched_at")
            stale = False
            if last:
                try: stale = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).days >= stale_days
                except ValueError: stale = True
            elif priority == "PRIORITY_A":
                stale = True
            if "NEW_REGULATORY_DISCLOSURE" in reasons:
                action = "REGULATORY_REVIEW_REQUIRED"
            elif any(reason in REFRESH_EVENTS for reason in reasons) or stale:
                action = "REFRESH_REQUIRED" if priority == "PRIORITY_A" else "PRIORITY_CHANGE_REVIEW"
            else:
                action = "NO_REFRESH_REQUIRED"
            reason = reasons or ([f"stale>{stale_days}d"] if stale else ["no material event"])
        queue.append({"firm_id": str(firm_id), "name": name, "priority_category": priority,
                      "acquisition_score": score, "action": action, "reasons": reason,
                      "previous_dataset_version": previous_version})
    return sorted(queue, key=lambda row: (row["action"] == "NO_REFRESH_REQUIRED", -float(row["acquisition_score"] or 0), row["firm_id"]))


def save_research_refresh_queue(queue: list[dict], dataset_version: str, output_dir: Path | None = None) -> Path:
    root = Path(output_dir or settings.EXPORTS_DIR / "research_refresh" / dataset_version)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "research_refresh_queue.json"
    path.write_text(json.dumps({"dataset_version": dataset_version, "generated_at": datetime.now(timezone.utc).isoformat(), "queue": queue}, indent=2, default=str) + "\n")
    return path

