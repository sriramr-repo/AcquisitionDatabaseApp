"""Markdown dossier generation from Gold V1 facts and research enrichment."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from src.config import settings
from src.gold_v1 import gold_v1_table_name
from src.research import ResearchRepository


def dossier_filename(firm_id: str, firm_name: str) -> str:
    """Return a deterministic, filesystem-safe dossier filename."""
    safe = re.sub(r"[^a-z0-9]+", "_", firm_name.lower()).strip("_")
    return f"{firm_id}_{safe}.md"


def _money(value: Any) -> str:
    if value is None:
        return "Unknown"
    number = float(value)
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    return f"${number:,.0f}"


def _percent(numerator: Any, denominator: Any) -> str:
    if numerator is None or denominator in (None, 0):
        return "Unknown"
    return f"{float(numerator) / float(denominator) * 100:.1f}%"


def _codes(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _value(record: dict[str, Any], field: str, default: str = "Unknown") -> str:
    value = record.get(field)
    return default if value in (None, "") else str(value)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- Unknown / not established"


def generate_target_dossier(
    firm_id: str,
    dataset_version: str,
    *,
    research_repository: ResearchRepository | None = None,
    duckdb_path: Path | str | None = None,
    output_dir: Path | None = None,
    draft: bool = False,
) -> Path:
    """Generate one deterministic dossier without writing Gold or Silver data."""
    repository = research_repository or ResearchRepository()
    research = repository.get_research_record(firm_id, dataset_version)
    if research is None:
        raise KeyError("Research record does not exist")
    sources = repository.list_research_sources(firm_id, dataset_version)
    connection = duckdb.connect(str(duckdb_path or settings.DUCKDB_FILE), read_only=True)
    try:
        table = gold_v1_table_name(dataset_version)
        row = connection.execute(
            f'SELECT * FROM "{table}" WHERE firm_id = ?', [firm_id]
        ).fetchone()
        if row is None:
            raise KeyError("Firm does not exist in Gold V1")
        columns = [item[0] for item in connection.execute(f'DESCRIBE "{table}"').fetchall()]
        gold = dict(zip(columns, row))
    finally:
        connection.close()

    aum = gold.get("total_aum")
    discretionary_share = _percent(gold.get("discretionary_aum"), aum)
    screening_reasons = _codes(gold.get("reason_codes"))
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lines = [
        f"# Target Dossier — {gold.get('name', firm_id)}",
        "",
        f"- Dataset version: `{dataset_version}`",
        f"- Firm ID: `{firm_id}`",
        f"- Generated at: `{generated_at}`",
        "",
    ]
    if draft:
        lines.extend([
            "> **Analyst Review Required:** This is a factual-enrichment draft. Founder status, ownership interpretation, succession, strategic fit, transition feasibility, valuation, and outreach recommendation remain unpopulated pending analyst review.",
            "",
        ])
    lines.extend([
        "## 1. Executive Snapshot",
        "",
        f"- **Firm:** {gold.get('name', 'Unknown')} ",
        f"- **AUM (SEC-derived):** {_money(aum)}",
        f"- **Acquisition score (Gold V1):** {_value(gold, 'acquisition_score')}",
        f"- **Priority:** {_value(gold, 'priority_category')}",
        f"- **Research status:** {_value(research, 'research_status')}",
        f"- **Screening summary (structured):** {_money(aum)} AUM; {discretionary_share} discretionary; {_value(gold, 'employee_count')} employees; {_value(gold, 'advisory_employee_count')} advisory employees.",
        "",
        "## 2. Why SCM Should Care",
        "",
        "**Structured facts:**",
        _bullets(screening_reasons),
        "",
        f"**Analyst assessment — strategic fit:** {_value(research, 'strategic_fit_assessment')}",
        f"{_value(research, 'strategic_fit_notes', 'No strategic-fit assessment recorded.')}",
        "",
        f"**Analyst assessment — succession:** {_value(research, 'succession_readiness_assessment')}",
        f"{_value(research, 'succession_notes', 'No succession assessment recorded.')}",
        "",
        "## 3. Firm Profile",
        "",
        "**SEC-derived facts:**",
        _bullets([
            f"Organization type: {_value(gold, 'organization_type')}",
            f"State / SEC region: {_value(gold, 'organization_state')} / {_value(gold, 'sec_region')}",
            f"Discretionary AUM: {_money(gold.get('discretionary_aum'))} ({discretionary_share})",
            f"Accounts: {_value(gold, 'total_account_count')} total; {_value(gold, 'discretionary_account_count')} discretionary",
            f"Client model flags: individuals/small businesses={_value(gold, 'advises_individuals_or_small_businesses')}; financial planning={_value(gold, 'provides_financial_planning')}",
            f"Staffing: {_value(gold, 'employee_count')} employees; {_value(gold, 'advisory_employee_count')} advisory employees",
        ]),
        "",
        "**Research facts:**",
        _bullets([
            f"Client niche: {_value(research, 'client_niche')}",
            f"Geographic focus: {_value(research, 'geographic_focus')}",
            f"Specialty niche: {_value(research, 'specialty_niche')}",
        ]),
        "",
        "## 4. Founder & Ownership",
        "",
        "**Research facts:**",
        _bullets([
            f"Founder: {_value(research, 'founder_name')}",
            f"Leadership role: {_value(research, 'founder_role')}",
            f"Leadership profile: {_value(research, 'founder_profile_notes')}",
        ]),
        "",
        "**Analyst assessment:**",
        _bullets([
            f"Ownership type / summary: {_value(research, 'ownership_type')} / {_value(research, 'ownership_summary')}",
            f"Closely-held assessment: {_value(research, 'closely_held_assessment')}",
        ]),
        "",
        "## 5. Succession Assessment",
        "",
        _bullets([
            f"Readiness assessment: {_value(research, 'succession_readiness_assessment')}",
            f"Signal strength: {_value(research, 'succession_signal_strength')}",
            f"Visible internal successor: {_value(research, 'visible_internal_successor')}",
            f"Successor: {_value(research, 'successor_name')}",
            f"Notes: {_value(research, 'succession_notes')}",
        ]),
        "",
        "## 6. Economics",
        "",
        "**Estimate:**",
        _bullets([
            f"Estimated revenue: {_money(research.get('estimated_revenue')) if research.get('estimated_revenue') is not None else 'Unknown'}",
            f"Method: {_value(research, 'revenue_estimation_method')}",
            f"Estimated EBITDA: {_money(research.get('estimated_ebitda')) if research.get('estimated_ebitda') is not None else 'Unknown'}",
            f"Estimated valuation range: {_money(research.get('estimated_valuation_low')) if research.get('estimated_valuation_low') is not None else 'Unknown'} to {_money(research.get('estimated_valuation_high')) if research.get('estimated_valuation_high') is not None else 'Unknown'}",
            f"Economics confidence: {_value(research, 'economics_confidence')}",
        ]),
        "",
        "## 7. Investment & Custodian Fit",
        "",
        "**Research facts:**",
        _bullets([
            f"Investment philosophy: {_value(research, 'investment_philosophy')}",
            f"Portfolio approach: {_value(research, 'portfolio_management_approach')}",
            f"Primary custodian: {_value(research, 'primary_custodian')}",
            f"Custodian confidence: {_value(research, 'custodian_confidence')}",
        ]),
        "",
        f"**Analyst assessment — investment model fit:** {_value(research, 'investment_model_fit')}",
        _value(research, 'investment_model_fit_notes', 'No investment-model assessment recorded.'),
        "",
        "## 8. Risks",
        "",
        _bullets([
            f"Regulatory: Gold V1 regulatory review flag={_value(gold, 'regulatory_review_flag')}; Item 11 disclosure={_value(gold, 'has_item_11_disclosure')}",
            f"Integration: {_value(research, 'integration_risks')}",
            "Cultural and operational fit: not determinable from reviewed public sources.",
        ]),
        "",
        "## 9. Recommended Next Action",
        "",
        _bullets([
            f"Recommendation: {_value(research, 'outreach_recommendation')}",
            f"Contact method: {_value(research, 'recommended_contact_method')}",
            f"Message angle: {_value(research, 'recommended_message_angle')}",
            f"Relationship path: {_value(research, 'relationship_path')}",
        ]),
        "",
        "## 10. Sources",
        "",
    ])
    for source in sources:
        title = source.get("source_title") or source.get("source_url") or source.get("source_type")
        url = source.get("source_url") or ""
        lines.append(
            f"- [{title}]({url}) — supports `{source.get('field_supported')}`; accessed {source.get('accessed_at') or 'unknown'}.")
    if not sources:
        lines.append("- No sources recorded.")
    lines.extend([
        "",
        "### Data classification",
        "",
        "- SEC-derived facts are labeled as structured facts.",
        "- Public-source statements are labeled as research facts.",
        "- Numeric economics are estimates with method/confidence fields.",
        "- Strategic, succession, ownership, and transition conclusions are analyst assessments.",
    ])
    root = Path(output_dir or (settings.EXPORTS_DIR / "dossiers" / dataset_version))
    root.mkdir(parents=True, exist_ok=True)
    path = root / dossier_filename(firm_id, str(gold.get("name", firm_id)))
    path.write_text("\n".join(lines) + "\n")
    return path
