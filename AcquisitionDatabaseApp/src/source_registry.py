"""Public-source taxonomy and Form ADV definition metadata.

This module contains source metadata only.  It does not fetch external pages,
accept analyst observations, or change Silver/Gold records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceDefinition:
    source_type: str
    authority: str
    title: str
    url: str | None
    collection_mode: str
    description: str


SOURCE_DEFINITIONS: dict[str, SourceDefinition] = {
    "historical_adv": SourceDefinition(
        "historical_adv", "SEC", "Historical Form ADV data",
        "https://www.sec.gov/foia-services/frequently-requested-documents/form-adv-data",
        "metadata_and_batch_csv", "Historical Form ADV Part 1/2 tables for longitudinal analysis.",
    ),
    "iapd": SourceDefinition(
        "iapd", "SEC/FINRA", "Investment Adviser Public Disclosure",
        "https://adviserinfo.sec.gov/", "metadata_and_analyst_review",
        "Current adviser filing, registration, and official document lookup.",
    ),
    "adv_part1_definitions": SourceDefinition(
        "adv_part1_definitions", "SEC", "Form ADV Part 1A definitions",
        "https://www.sec.gov/files/formadv-part1a_1.pdf", "reference_only",
        "Versioned field definitions and canonical mapping references.",
    ),
    "adv_part2a": SourceDefinition(
        "adv_part2a", "SEC/FINRA", "Form ADV Part 2A brochure",
        "https://adviserinfo.sec.gov/", "metadata_and_analyst_review",
        "Firm brochure evidence for biographies, strategy, fees, and custody clues.",
    ),
    "official_website": SourceDefinition(
        "official_website", "Firm", "Official firm website",
        None, "metadata_and_analyst_review",
        "Firm-controlled public pages for leadership, services, niche, and contacts.",
    ),
    "public_biography": SourceDefinition(
        "public_biography", "Public source", "Public professional biography",
        None, "metadata_and_analyst_review",
        "Public bios used to corroborate role, tenure, and leadership continuity.",
    ),
    "state_record": SourceDefinition(
        "state_record", "State regulator", "State regulatory or business record",
        "https://www.nasaa.org/about-us/contact-your-regulator/", "analyst_review",
        "Jurisdiction-specific registration and entity corroboration.",
    ),
    "brokercheck": SourceDefinition(
        "brokercheck", "FINRA", "FINRA BrokerCheck",
        "https://brokercheck.finra.org/", "analyst_review",
        "Broker-dealer overlap and public disciplinary review.",
    ),
    "business_registry": SourceDefinition(
        "business_registry", "State or public registry", "Public business registry",
        None, "analyst_review",
        "Legal entity status and ownership-related corroboration.",
    ),
    "relationship_referral": SourceDefinition(
        "relationship_referral", "SCM analyst", "Relationship or referral source",
        None, "manual_only",
        "Warm-introduction and relationship-path evidence entered by analysts.",
    ),
}

CORE_SOURCE_TYPES = (
    "historical_adv", "iapd", "adv_part2a", "official_website",
    "public_biography", "state_record", "brokercheck", "business_registry",
    "relationship_referral",
)

SOURCE_TASK_STATUSES = frozenset(
    {"NOT_STARTED", "DISCOVERED", "RETRIEVED", "REVIEW_REQUIRED", "ACCEPTED", "UNAVAILABLE", "FAILED", "STALE"}
)

OBSERVATION_STATUSES = frozenset({"PROPOSED", "ACCEPTED", "REJECTED", "CONFLICTING"})
OBSERVATION_VALUE_TYPES = frozenset({"FACT", "ESTIMATE", "ASSESSMENT"})
CONFIDENCE_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "VERIFIED"})


# Canonical fields that are useful for the first public-source pass.  The
# monthly SEC mapping remains the authority for the actual Silver columns.
FORM_ADV_FIELD_DEFINITIONS: dict[str, dict[str, str]] = {
    "firm_id": {"item": "Item 1", "description": "Organization CRD number"},
    "sec_number": {"item": "Item 1", "description": "SEC registration number"},
    "name": {"item": "Item 1", "description": "Legal or primary business name"},
    "organization_type": {"item": "Item 3", "description": "Form of organization"},
    "succession_indicator": {"item": "Item 4", "description": "Successions"},
    "total_aum": {"item": "Item 5.F(2)(c)", "description": "Total regulatory assets under management"},
    "discretionary_aum": {"item": "Item 5.F(2)(a)", "description": "Discretionary regulatory assets under management"},
    "non_discretionary_aum": {"item": "Item 5.F(2)(b)", "description": "Nondiscretionary regulatory assets under management"},
    "total_account_count": {"item": "Item 5.F(2)(f)", "description": "Total accounts"},
    "employee_count": {"item": "Item 5.A", "description": "Employees"},
    "advisory_employee_count": {"item": "Item 5.B(1)", "description": "Employees performing advisory functions"},
    "individual_client_aum": {"item": "Item 5.D(a)(3)", "description": "Individual client assets"},
    "hnw_client_aum": {"item": "Item 5.D(b)(3)", "description": "High-net-worth individual client assets"},
    "has_item_11_disclosure": {"item": "Item 11", "description": "Disclosure information indicator"},
}


def source_definition(source_type: str) -> SourceDefinition:
    try:
        return SOURCE_DEFINITIONS[source_type]
    except KeyError as exc:
        raise ValueError(f"Unknown source type: {source_type}") from exc


def source_url(source_type: str, *, firm_id: str | None = None, website: str | None = None) -> str | None:
    """Return a safe canonical landing URL, not an undocumented deep link."""
    if source_type == "official_website":
        return website or None
    return source_definition(source_type).url


def source_metadata(source_type: str) -> dict[str, Any]:
    definition = source_definition(source_type)
    return {
        "source_type": definition.source_type,
        "source_authority": definition.authority,
        "source_title": definition.title,
        "source_url": definition.url,
        "collection_mode": definition.collection_mode,
        "description": definition.description,
    }
