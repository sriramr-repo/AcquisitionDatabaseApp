"""Pure reconciliation policy for separately preserved monthly and live evidence."""
from datetime import date, datetime, timezone

VERSION = "iapd-reconcile-v3"


def _normalized_date(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat()
        except ValueError:
            continue
    return text


def source_stale(value, *, days=45, today=None):
    try:
        observed = date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return True
    age = ((today or datetime.now(timezone.utc).date()) - observed).days
    return age < 0 or age > days


def reconcile_values(monthly_rows, live, *, today=None):
    live = live or {}
    employers = []
    for row in monthly_rows:
        employer = {"crd": row.get("employer_firm_crd"), "name": row.get("employer_name"),
                    "registration_status": row.get("registration_status"), "registration_date": row.get("registration_date"),
                    "business_address": ", ".join(str(row[k]) for k in ("address_line_1", "address_line_2", "city", "state", "postal_code", "country") if row.get(k)) or None}
        if employer not in employers:
            employers.append(employer)
    primary = employers[0] if len(employers) == 1 else {}
    monthly = monthly_rows[0] if monthly_rows else {}
    conflicts = {}
    monthly_name = monthly.get("full_name")
    live_name = live.get("full_name")
    if monthly_name and live_name and monthly_name.casefold() != live_name.casefold():
        conflicts["full_name"] = {
            "reason": "NAME_MISMATCH_FOR_CRD", "monthly": monthly_name, "live": live_name,
            "monthly_source_url": monthly.get("source_url"), "live_source_url": live.get("source_url"),
            "monthly_observed_at": str(monthly.get("snapshot_date")), "live_observed_at": str(live.get("retrieved_at")),
        }
    live_crd = live.get("current_employer_crd")
    if employers and live_crd and live_crd not in {e["crd"] for e in employers}:
        conflicts["current_employer_crd"] = {
            "reason": "EMPLOYER_CRD_MISMATCH", "monthly": employers, "live": live_crd,
            "monthly_source_url": monthly.get("source_url"), "live_source_url": live.get("source_url"),
            "monthly_observed_at": str(monthly.get("snapshot_date")), "live_observed_at": str(live.get("retrieved_at")),
        }
    if primary.get("registration_status") and live.get("registration_status") not in (None, 'CURRENT_REGISTRATION_REPORTED') and primary["registration_status"].casefold() != live["registration_status"].casefold():
        conflicts["registration_status"] = {
            "reason": "REGISTRATION_STATUS_MISMATCH", "monthly": primary["registration_status"], "live": live["registration_status"],
            "monthly_source_url": monthly.get("source_url"), "live_source_url": live.get("source_url"),
            "monthly_observed_at": str(monthly.get("snapshot_date")), "live_observed_at": str(live.get("retrieved_at")),
        }
    if (primary.get("registration_date") and live.get("registration_date")
            and _normalized_date(primary["registration_date"]) != _normalized_date(live["registration_date"])):
        conflicts["registration_date"] = {"reason":"REGISTRATION_DATE_MISMATCH","monthly":primary["registration_date"],"live":live["registration_date"],"monthly_source_url":monthly.get("source_url"),"live_source_url":live.get("source_url")}
    if monthly.get("disclosure_summary") and live.get("disclosure_summary") and monthly["disclosure_summary"].casefold() != live["disclosure_summary"].casefold():
        conflicts["disclosure_summary"] = {"reason":"DISCLOSURE_MISMATCH","monthly":monthly["disclosure_summary"],"live":live["disclosure_summary"],"monthly_source_url":monthly.get("source_url"),"live_source_url":live.get("source_url")}
    effective = {"full_name": monthly.get("full_name") or live.get("full_name"), "current_employers": employers or (live.get('normalized_fields') or {}).get('current_employers', [])}
    provenance = {}
    for field, key in (("current_employer_crd", "crd"), ("current_employer_name", "name"), ("registration_status", "registration_status"), ("registration_date", "registration_date"), ("business_address", "business_address")):
        value = primary.get(key)
        # Multiple current employers are represented as a list, never guessed.
        same_employer = bool(primary.get("crd") and primary["crd"] == live_crd)
        use_live = value is None and (not employers or (same_employer and field == "business_address"))
        effective[field] = live.get(field) if use_live else value
        provenance[field] = "live_page" if use_live and effective[field] is not None else "monthly_feed"
    for field in ("phone", "website", "branch_locations"):
        effective[field] = live.get(field)
        provenance[field] = "live_page" if live.get(field) is not None else None
    effective["disclosure_summary"] = monthly.get("disclosure_summary") if monthly.get("disclosure_summary") is not None else live.get("disclosure_summary")
    provenance["disclosure_summary"] = "monthly_feed" if monthly.get("disclosure_summary") is not None else "live_page"
    for conflict in conflicts.values():
        conflict.setdefault("monthly_observed_at", str(monthly.get("snapshot_date")))
        conflict.setdefault("live_observed_at", str(live.get("retrieved_at")))
    effective["provenance"] = {key: {"source_type": source,
        "source_id": live.get("capture_id") if source == "live_page" else monthly.get("snapshot_id"),
        "observed_at": str(live.get("retrieved_at") if source == "live_page" else monthly.get("snapshot_date"))}
        for key, source in provenance.items() if source and effective.get(key) is not None}
    stale = source_stale(monthly.get("snapshot_date"), today=today) if monthly else source_stale(live.get("retrieved_at"), days=30, today=today)
    effective["stale"] = stale
    effective["reconciliation_version"] = VERSION
    freshness = "conflict" if conflicts else "missing" if not monthly and not live else "partial" if stale or (not monthly and live.get("confidence") != "HIGH") else "monthly_confirmed" if monthly else "live_confirmed"
    return effective, freshness, conflicts
