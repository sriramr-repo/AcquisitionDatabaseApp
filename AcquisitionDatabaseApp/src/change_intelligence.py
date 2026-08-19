"""Business-facing month-over-month change intelligence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from src.config import settings
from src.gold_v1 import gold_v1_table_name


TARGET_LOW = 20_000_000
TARGET_HIGH = 100_000_000


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def compare_gold_versions(previous_version: str, current_version: str,
                          *, duckdb_path: Path | str | None = None) -> dict[str, Any]:
    connection = duckdb.connect(str(duckdb_path or settings.DUCKDB_FILE), read_only=True)
    try:
        old_table, new_table = gold_v1_table_name(previous_version), gold_v1_table_name(current_version)
        available = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
        if old_table not in available or new_table not in available:
            return {"previous_version": previous_version, "current_version": current_version,
                    "events": [], "error": "required Gold V1 table is missing"}
        old = connection.execute(f'SELECT * FROM "{old_table}"').df().set_index("firm_id")
        new = connection.execute(f'SELECT * FROM "{new_table}"').df().set_index("firm_id")
    finally:
        connection.close()

    events: list[dict[str, Any]] = []
    for firm_id in sorted(set(new.index) - set(old.index), key=str):
        row = new.loc[firm_id]
        if row.get("priority_category") == "PRIORITY_A":
            events.append({"event_type": "NEW_PRIORITY_A", "firm_id": str(firm_id), "details": {"name": row.get("name")}})
    for firm_id in sorted(set(old.index) - set(new.index), key=str):
        events.append({"event_type": "REMOVED_FIRM", "firm_id": str(firm_id), "details": {}})

    common = set(old.index) & set(new.index)
    tracked = ["registration_status", "total_aum", "discretionary_aum", "total_account_count",
               "employee_count", "advisory_employee_count", "priority_category", "has_item_11_disclosure",
               "organization_type", "individual_hnw_client_aum"]
    for firm_id in sorted(common, key=str):
        before, after = old.loc[firm_id], new.loc[firm_id]
        name = after.get("name")
        def changed(column: str) -> bool:
            if column not in old.columns or column not in new.columns:
                return False
            a, b = before.get(column), after.get(column)
            if a != a and b != b:  # both NaN
                return False
            return (a if a == a else None) != (b if b == b else None)
        def add(event_type: str, details: dict[str, Any]) -> None:
            events.append({"event_type": event_type, "firm_id": str(firm_id), "name": name, "details": details})
        if changed("priority_category"):
            old_p, new_p = before.get("priority_category"), after.get("priority_category")
            mapping = {("PRIORITY_B", "PRIORITY_A"): "PRIORITY_B_TO_A", ("PRIORITY_A", "PRIORITY_B"): "PRIORITY_A_TO_B", ("PRIORITY_A", "PRIORITY_C"): "PRIORITY_A_TO_C"}
            if (old_p, new_p) in mapping: add(mapping[(old_p, new_p)], {"old": old_p, "new": new_p})
        aum_old, aum_new = _number(before.get("total_aum")), _number(after.get("total_aum"))
        if aum_old and aum_new and aum_old > 0:
            delta = (aum_new - aum_old) / aum_old
            if delta <= -0.20: add("MATERIAL_AUM_DECLINE", {"old": aum_old, "new": aum_new, "change_pct": delta})
            elif delta >= 0.20: add("MATERIAL_AUM_GROWTH", {"old": aum_old, "new": aum_new, "change_pct": delta})
        if aum_old is not None and aum_new is not None:
            old_band, new_band = TARGET_LOW <= aum_old <= TARGET_HIGH, TARGET_LOW <= aum_new <= TARGET_HIGH
            if not old_band and new_band: add("ENTERED_TARGET_AUM_BAND", {"old": aum_old, "new": aum_new})
            if old_band and not new_band: add("EXITED_TARGET_AUM_BAND", {"old": aum_old, "new": aum_new})
        if changed("has_item_11_disclosure") and bool(after.get("has_item_11_disclosure")): add("NEW_REGULATORY_DISCLOSURE", {})
        for column in ("registration_status", "organization_type", "total_account_count", "individual_hnw_client_aum"):
            if changed(column): add(f"{column.upper()}_CHANGE", {"old": before.get(column), "new": after.get(column)})
        for column in ("employee_count", "advisory_employee_count"):
            if changed(column): add("MATERIAL_STAFFING_CHANGE", {"field": column, "old": before.get(column), "new": after.get(column)})
    return {"previous_version": previous_version, "current_version": current_version,
            "events": events, "event_counts": {key: sum(e["event_type"] == key for e in events) for key in sorted({e["event_type"] for e in events})}}


def save_change_intelligence(report: dict[str, Any], output_dir: Path | None = None) -> Path:
    root = Path(output_dir or settings.EXPORTS_DIR / "change_intelligence" / report["current_version"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / "monthly_change_intelligence.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return path

