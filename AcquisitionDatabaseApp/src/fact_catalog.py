"""Versioned dashboard fact dictionary and source-lineage metadata."""
from __future__ import annotations

from dataclasses import dataclass, asdict

CATALOG_VERSION = "scm-fact-catalog-v2"


@dataclass(frozen=True)
class FactDefinition:
    field_key: str
    display_label: str
    short_definition: str
    category: str
    value_type: str
    primary_source_type: str
    primary_source_field: str | None
    extraction_method: str
    dashboard_section: str
    display_order: int
    data_class: str = "SEC_FACT"
    form_item: str | None = None
    fallback_source_type: str | None = None
    null_meaning: str = "Not reported or unavailable; never equivalent to zero."
    editable: bool = False
    requires_evidence: bool = False
    used_in_scoring: bool = False

    def record(self) -> dict:
        return {**asdict(self), "definition_version": CATALOG_VERSION, "active": True}


def _adv(key: str, label: str, definition: str, item: str, source: str, value_type: str, order: int) -> FactDefinition:
    return FactDefinition(key, label, definition, "FORM_ADV", value_type, "SEC_IA_BULK", source, "STRUCTURED_CSV", "Form ADV", order, form_item=item)


FACT_DEFINITIONS = [
    FactDefinition("firm.name", "Firm name", "Current primary business name.", "IDENTITY", "text", "SEC_IA_BULK", "Primary Business Name", "STRUCTURED_CSV", "Business profile", 10),
    FactDefinition("firm.crd", "CRD number", "Firm Central Registration Depository identifier.", "IDENTITY", "text", "SEC_IA_BULK", "Organization CRD#", "STRUCTURED_CSV", "Business profile", 20),
    FactDefinition("firm.sec_number", "SEC number", "Firm SEC registration number.", "IDENTITY", "text", "SEC_IA_BULK", "SEC#", "STRUCTURED_CSV", "Business profile", 30),
    FactDefinition("score.acquisition", "Acquisition score", "SCM Acquisition V2 screening score.", "SCORING", "number", "GOLD_V1", "acquisition_score", "DETERMINISTIC_MODEL", "Why this firm", 10, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.priority", "Priority", "Priority category assigned by SCM Acquisition V2.", "SCORING", "text", "GOLD_V1", "priority_category", "DETERMINISTIC_MODEL", "Why this firm", 20, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.aum_fit", "AUM fit score", "Fit to the target and preferred AUM bands.", "SCORING", "number", "GOLD_V1", "aum_fit_score", "DETERMINISTIC_MODEL", "Why this firm", 30, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.client_fit", "Client fit score", "Fit based on individual and HNW client concentration.", "SCORING", "number", "GOLD_V1", "client_fit_score", "DETERMINISTIC_MODEL", "Why this firm", 40, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.discretionary_fit", "Discretionary fit score", "Fit based on discretionary AUM share and amount.", "SCORING", "number", "GOLD_V1", "discretionary_fit_score", "DETERMINISTIC_MODEL", "Why this firm", 50, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.advisory_model_fit", "Advisory model fit score", "Fit based on reported activities and model complexity.", "SCORING", "number", "GOLD_V1", "advisory_model_fit_score", "DETERMINISTIC_MODEL", "Why this firm", 60, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.regulatory_quality", "Regulatory quality score", "Screening component based on Item 11 review signals.", "SCORING", "number", "GOLD_V1", "regulatory_quality_score", "DETERMINISTIC_MODEL", "Why this firm", 70, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.practice_complexity", "Practice complexity score", "Screening component based on team and control structure.", "SCORING", "number", "GOLD_V1", "practice_complexity_score", "DETERMINISTIC_MODEL", "Why this firm", 80, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.account_practice_fit", "Account practice fit score", "Fit based on account scale, average size, and discretion.", "SCORING", "number", "GOLD_V1", "account_practice_fit_score", "DETERMINISTIC_MODEL", "Why this firm", 90, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("score.reason_codes", "Reason codes", "Discrete SCM Acquisition V2 explanations.", "SCORING", "list", "GOLD_V1", "reason_codes", "DETERMINISTIC_MODEL", "Why this firm", 100, data_class="DERIVED_SCORE", used_in_scoring=True),
    FactDefinition("firm.website", "Firm website", "Website reported on Form ADV.", "IDENTITY", "url", "SEC_IA_BULK", "Website Address", "STRUCTURED_CSV", "Business profile", 40),
    FactDefinition("firm.organization_state", "Organization state", "State or jurisdiction of organization.", "IDENTITY", "text", "SEC_IA_BULK", "Organization State", "STRUCTURED_CSV", "Business profile", 50),
    FactDefinition("office.main_address", "Main office address", "Main office address reported on Form ADV.", "CONTACT", "address", "SEC_IA_BULK", "Main Office Street Address 1..Country", "STRUCTURED_CSV", "Contacts", 10),
    FactDefinition("office.main_phone", "Main office telephone", "Main office telephone reported on Form ADV.", "CONTACT", "phone", "SEC_IA_BULK", "Main Office Telephone Number", "STRUCTURED_CSV", "Contacts", 20),
    FactDefinition("iapd.current_representatives", "Current IAPD representatives", "Individuals linked to the firm in the official current IAPD feed.", "IAPD", "list", "IAPD_INDIVIDUAL_FEED", "CurrentEmployment", "STRUCTURED_XML", "IAPD personnel", 10),
    FactDefinition("iapd.principals", "Form ADV principals and owners", "Individuals or entities reported in Schedule A/B.", "IAPD", "list", "FORM_ADV_SCHEDULE_AB", "Schedule A/B", "STRUCTURED_CSV", "IAPD personnel", 20),
    _adv("adv.item_1o_over_1b", "$1B+ balance-sheet assets", "Whether fiscal-year-end total firm assets were at least $1 billion; this is not client AUM.", "1.O", "1O", "boolean", 10),
    _adv("adv.item_1o_asset_band", "Balance-sheet asset band", "Reported Item 1.O total-assets band.", "1.O", "1O - If yes, approx. amount of assets", "text", 20),
    _adv("adv.sec_registration_basis", "SEC registration basis", "Checked legal basis or bases for SEC registration.", "2.A", "2A(1)..2A(13)", "list", 30),
    _adv("adv.succession_indicator", "Succession filing", "Whether this filing reports succession to a registered adviser business.", "4.A", "4A", "boolean", 40),
    _adv("adv.succession_date", "Succession date", "Date of the succession reported on this filing.", "4.B", "4B", "date", 50),
    _adv("adv.employee_count", "Employees", "Approximate non-clerical full- and part-time employee count.", "5.A", "5A", "integer", 60),
    _adv("adv.advisory_employee_count", "Advisory employees", "Employees performing investment advisory functions, including research.", "5.B(1)", "5B(1)", "integer", 70),
    _adv("adv.broker_dealer_rep_count", "Broker-dealer representatives", "Employees registered as broker-dealer representatives.", "5.B(2)", "5B(2)", "integer", 80),
    _adv("adv.state_iar_count", "State IARs", "Employees registered as investment adviser representatives with state authorities.", "5.B(3)", "5B(3)", "integer", 90),
    _adv("adv.other_adviser_iar_count", "Other-adviser IARs", "Employees registered as IARs for another adviser.", "5.B(4)", "5B(4)", "integer", 100),
    _adv("adv.insurance_agent_count", "Insurance agents", "Employees licensed as insurance agents.", "5.B(5)", "5B(5)", "integer", 110),
    _adv("adv.solicitor_count", "Solicitors", "Firms or persons soliciting advisory clients on the adviser's behalf.", "5.B(6)", "5B(6)", "integer", 120),
    _adv("adv.client_categories", "Client categories", "Client count, fewer-than-five flag, and AUM by Item 5.D category.", "5.D", "5D(a..n)(1..3)", "list", 130),
    _adv("adv.compensation_arrangements", "Compensation arrangements", "Checked methods used to compensate the adviser.", "5.E", "5E(1)..5E(7)", "list", 140),
    _adv("adv.total_aum", "Regulatory AUM", "Total regulatory assets under management.", "5.F(2)(c)", "5F(2)(c)", "money", 150),
    _adv("adv.total_account_count", "Accounts", "Total accounts included in regulatory AUM.", "5.F(2)(f)", "5F(2)(f)", "integer", 160),
    _adv("adv.advisory_activities", "Advisory activities", "Checked advisory service types.", "5.G", "5G(1)..5G(12)", "list", 170),
    _adv("adv.sma_custodian_reporting_required", "SMA custodian schedule", "Whether one or more custodians hold at least 10% of separately managed account AUM.", "5.K(4)", "5K(4)", "boolean", 180),
    FactDefinition("adv.custodians", "SMA custodians", "Schedule D 5.K.(3) custodian details.", "FORM_ADV", "list", "FORM_ADV_PDF", "Schedule D 5.K.(3)", "LOCAL_OCR_REVIEW_GATED", "Form ADV", 190, form_item="Schedule D 5.K.(3)", requires_evidence=True),
    FactDefinition("adv.ownership_control", "Ownership and control", "Direct and indirect owners, executive officers, ownership bands, and control-person indicators.", "FORM_ADV", "list", "FORM_ADV_SCHEDULE_AB", "Schedule A/B", "STRUCTURED_SCHEDULE_OR_PDF_REVIEW_GATED", "Ownership and control", 10, form_item="Schedule A/B", requires_evidence=True),
    FactDefinition("adv.other_business_activities", "Other business activities", "Other reported financial-industry and non-investment-advisory business activities.", "FORM_ADV", "list", "FORM_ADV_PDF", "Item 6", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "Affiliations and conflicts", 10, form_item="6", requires_evidence=True),
    FactDefinition("adv.financial_affiliations", "Financial-industry affiliations", "Reported related financial businesses and private-fund relationships.", "FORM_ADV", "list", "FORM_ADV_PDF", "Item 7 / Schedule D", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "Affiliations and conflicts", 20, form_item="7", requires_evidence=True),
    FactDefinition("adv.client_transaction_conflicts", "Client-transaction indicators", "Reported proprietary interests, principal transactions, agency crosses, and related transaction practices.", "FORM_ADV", "list", "FORM_ADV_PDF", "Item 8", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "Affiliations and conflicts", 30, form_item="8", requires_evidence=True),
    FactDefinition("adv.custody_arrangements", "Custody arrangements", "Reported adviser or related-person custody and applicable safeguarding arrangements.", "FORM_ADV", "object", "FORM_ADV_PDF", "Item 9 / Schedule D", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "SMA and custody", 10, form_item="9", requires_evidence=True),
    FactDefinition("adv.sma_structure", "SMA structure", "Separately managed account assets, asset categories, borrowing, derivatives, and custodian concentration.", "FORM_ADV", "object", "FORM_ADV_PDF", "Item 5.K / Schedule D", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "SMA and custody", 20, form_item="5.K", requires_evidence=True),
    FactDefinition("adv.private_funds", "Private funds", "Reported private funds and service-provider relationships from Item 7.B and Schedule D.", "FORM_ADV", "list", "FORM_ADV_PDF", "Item 7.B / Schedule D", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "Private funds", 10, form_item="7.B", requires_evidence=True),
    FactDefinition("adv.disclosure_details", "Disclosure details", "Source-backed details for reported criminal, regulatory, civil, and administrative disclosure events.", "FORM_ADV", "list", "FORM_ADV_PDF", "Item 11 / DRPs", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "Regulatory review", 10, form_item="11", requires_evidence=True),
    FactDefinition("adv.additional_offices", "Additional offices", "Additional office locations and reported activities from Schedule D.", "FORM_ADV", "list", "FORM_ADV_PDF", "Schedule D 1.F", "PDF_STRUCTURED_EXTRACTION_REVIEW_GATED", "Operating footprint", 10, form_item="Schedule D 1.F", requires_evidence=True),
    FactDefinition("adv.brochure_intelligence", "ADV Part 2A intelligence", "Source-backed proposed facts from the firm's current brochure, including services, fees, methods, brokerage, referrals, and custody narrative.", "RESEARCH", "object", "ADV_PART_2A", "Items 4-18", "FIRECRAWL_LANGCHAIN_REVIEW_GATED", "Brochure intelligence", 10, data_class="PUBLIC_SOURCE_FACT", form_item="Part 2A", fallback_source_type="OFFICIAL_FIRM_WEBSITE", requires_evidence=True),
    FactDefinition("research.status", "Research status", "Progress of analyst enrichment; separate from outreach and seller intent.", "WORKFLOW", "status", "ANALYST_WORKFLOW", "firm_research.research_status", "USER_ENTRY", "Research", 10, data_class="WORKFLOW_STATE", editable=True),
    FactDefinition("research.founder", "Founder or principal", "Accepted source-backed founder or principal identity.", "RESEARCH", "text", "ACCEPTED_RESEARCH", "founder_name", "ANALYST_OR_REVIEWED_AGENT", "Research", 20, data_class="PUBLIC_SOURCE_FACT", editable=True, requires_evidence=True),
    FactDefinition("research.ownership", "Ownership summary", "Accepted evidence-backed ownership description.", "RESEARCH", "text", "ACCEPTED_RESEARCH", "ownership_summary", "ANALYST_OR_REVIEWED_AGENT", "Research", 30, data_class="PUBLIC_SOURCE_FACT", editable=True, requires_evidence=True),
    FactDefinition("research.strategic_fit", "Strategic fit", "Analyst assessment; not an SEC fact or Gold score.", "RESEARCH", "text", "ANALYST_WORKFLOW", "strategic_fit_assessment", "USER_ENTRY", "Research", 40, data_class="ANALYST_ASSESSMENT", editable=True, requires_evidence=True),
    FactDefinition("research.primary_custodian", "Primary custodian", "Accepted source-backed custodian research value.", "RESEARCH", "text", "ACCEPTED_RESEARCH", "primary_custodian", "ANALYST_OR_REVIEWED_AGENT", "Research", 50, data_class="PUBLIC_SOURCE_FACT", editable=True, requires_evidence=True),
    FactDefinition("outreach.status", "Outreach status", "Preparation and engagement workflow; no message is sent by this value.", "WORKFLOW", "status", "ANALYST_WORKFLOW", "outreach_targets.status", "USER_ENTRY", "Outreach", 10, data_class="WORKFLOW_STATE", editable=True),
    FactDefinition("seller_intent.status", "Seller intent", "Evidence-backed current willingness or process status, confirmed by a user.", "SELLER_INTENT", "status", "VERIFIED_COMMUNICATION", "seller_intent_evidence", "ALGORITHM_PROPOSED_USER_CONFIRMED", "Seller intent", 10, data_class="ANALYST_ASSESSMENT", editable=True, requires_evidence=True),
]


def records() -> list[dict]:
    return [definition.record() for definition in FACT_DEFINITIONS]
