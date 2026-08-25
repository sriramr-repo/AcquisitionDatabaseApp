from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, validator


class OfficeType(str, Enum):
    MAIN = "MAIN"
    MAIL = "MAIL"
    BOOKS_RECORDS = "BOOKS_RECORDS"


class Firm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firm_id: str
    sec_number: Optional[str] = None
    cik_number: Optional[str] = None
    additional_crd_numbers: Optional[str] = None
    name: str
    primary_business_name: Optional[str] = None
    sec_region: Optional[str] = None
    website_address: Optional[str] = None
    firm_type: Optional[str] = None
    umbrella_registration: Optional[bool] = None
    sec_current_status: Optional[str] = None
    sec_status_effective_date: Optional[datetime] = None
    jurisdiction_notice_filed_effective_date: Optional[datetime] = None
    latest_adv_filing_date: Optional[datetime] = None
    form_version: Optional[str] = None
    total_aum: Optional[Decimal] = None
    discretionary_aum: Optional[Decimal] = None
    non_discretionary_aum: Optional[Decimal] = None
    discretionary_account_count: Optional[int] = None
    non_discretionary_account_count: Optional[int] = None
    total_account_count: Optional[int] = None
    organization_type: Optional[str] = None
    organization_type_other: Optional[str] = None
    organization_state: Optional[str] = None
    organization_country: Optional[str] = None
    has_unlisted_control_person: Optional[bool] = None
    has_related_person_control: Optional[bool] = None
    under_common_control: Optional[bool] = None
    shares_supervised_persons: Optional[bool] = None
    shares_location: Optional[bool] = None
    individual_client_count: Optional[int] = None
    individual_client_fewer_than_five: Optional[bool] = None
    individual_client_aum: Optional[Decimal] = None
    hnw_client_count: Optional[int] = None
    hnw_client_fewer_than_five: Optional[bool] = None
    hnw_client_aum: Optional[Decimal] = None
    banking_client_count: Optional[int] = None
    banking_client_fewer_than_five: Optional[bool] = None
    banking_client_aum: Optional[Decimal] = None
    investment_company_client_count: Optional[int] = None
    investment_company_client_aum: Optional[Decimal] = None
    business_development_company_client_count: Optional[int] = None
    business_development_company_client_aum: Optional[Decimal] = None
    pooled_investment_vehicle_client_count: Optional[int] = None
    pooled_investment_vehicle_client_fewer_than_five: Optional[bool] = None
    pooled_investment_vehicle_client_aum: Optional[Decimal] = None
    pension_profit_sharing_client_count: Optional[int] = None
    pension_profit_sharing_client_fewer_than_five: Optional[bool] = None
    pension_profit_sharing_client_aum: Optional[Decimal] = None
    charitable_organization_client_count: Optional[int] = None
    charitable_organization_client_fewer_than_five: Optional[bool] = None
    charitable_organization_client_aum: Optional[Decimal] = None
    state_municipal_entity_client_count: Optional[int] = None
    state_municipal_entity_client_fewer_than_five: Optional[bool] = None
    state_municipal_entity_client_aum: Optional[Decimal] = None
    other_investment_adviser_client_count: Optional[int] = None
    other_investment_adviser_client_fewer_than_five: Optional[bool] = None
    other_investment_adviser_client_aum: Optional[Decimal] = None
    insurance_company_client_count: Optional[int] = None
    insurance_company_client_fewer_than_five: Optional[bool] = None
    insurance_company_client_aum: Optional[Decimal] = None
    sovereign_wealth_fund_client_count: Optional[int] = None
    sovereign_wealth_fund_client_fewer_than_five: Optional[bool] = None
    sovereign_wealth_fund_client_aum: Optional[Decimal] = None
    corporation_other_business_client_count: Optional[int] = None
    corporation_other_business_client_fewer_than_five: Optional[bool] = None
    corporation_other_business_client_aum: Optional[Decimal] = None
    other_client_count: Optional[int] = None
    other_client_fewer_than_five: Optional[bool] = None
    other_client_aum: Optional[Decimal] = None
    other_client_type_description: Optional[str] = None
    individual_hnw_client_count: Optional[int] = None
    individual_hnw_client_aum: Optional[Decimal] = None
    provides_financial_planning: Optional[bool] = None
    advises_individuals_or_small_businesses: Optional[bool] = None
    advises_investment_companies: Optional[bool] = None
    advises_pooled_investment_vehicles: Optional[bool] = None
    advises_institutional_clients: Optional[bool] = None
    provides_pension_consulting: Optional[bool] = None
    selects_other_advisers: Optional[bool] = None
    publishes_periodicals_or_newsletters: Optional[bool] = None
    provides_security_ratings_or_pricing: Optional[bool] = None
    provides_market_timing: Optional[bool] = None
    provides_educational_seminars_or_workshops: Optional[bool] = None
    provides_other_advisory_services: Optional[bool] = None
    succession_indicator: Optional[bool] = None
    succession_date: Optional[datetime] = None
    employee_count: Optional[int] = None
    advisory_employee_count: Optional[int] = None
    broker_dealer_rep_count: Optional[int] = None
    state_iar_count: Optional[int] = None
    other_adviser_iar_count: Optional[int] = None
    insurance_agent_count: Optional[int] = None
    solicitor_count: Optional[int] = None
    other_regulatory_aum: Optional[Decimal] = None
    private_fund_count: Optional[int] = None
    hedge_fund_count: Optional[int] = None
    pe_fund_count: Optional[int] = None
    real_estate_fund_count: Optional[int] = None
    vc_fund_count: Optional[int] = None
    liquidity_fund_count: Optional[int] = None
    total_relying_advisers: Optional[int] = None
    total_additional_crd_numbers: Optional[int] = None
    total_cik_numbers: Optional[int] = None
    total_website_addresses: Optional[int] = None
    total_books_and_records_locations: Optional[int] = None
    disciplinary_event_count: Optional[int] = None
    civil_action_count: Optional[int] = None
    bonding_requirement_count: Optional[int] = None
    other_regulatory_event_count: Optional[int] = None
    financial_condition_event_count: Optional[int] = None
    affiliation_change_count: Optional[int] = None
    public_company_control_person_count: Optional[int] = None
    has_item_11_disclosure: Optional[bool] = None
    has_felony_conviction: Optional[bool] = None
    has_felony_charge: Optional[bool] = None
    has_misdemeanor_investment_or_fraud_conviction: Optional[bool] = None
    has_misdemeanor_investment_or_fraud_charge: Optional[bool] = None
    has_sec_cftc_false_statement: Optional[bool] = None
    has_sec_cftc_violation: Optional[bool] = None
    has_sec_cftc_authorization_restriction_cause: Optional[bool] = None
    has_sec_cftc_investment_order: Optional[bool] = None
    has_sec_cftc_penalty_or_cease_desist: Optional[bool] = None
    has_other_regulator_false_statement: Optional[bool] = None
    has_other_regulator_violation: Optional[bool] = None
    has_other_regulator_authorization_restriction_cause: Optional[bool] = None
    has_other_regulator_investment_order: Optional[bool] = None
    has_other_regulator_registration_or_association_restriction: Optional[bool] = None
    has_sro_false_statement: Optional[bool] = None
    has_sro_rule_violation: Optional[bool] = None
    has_sro_authorization_restriction_cause: Optional[bool] = None
    has_sro_discipline: Optional[bool] = None
    has_professional_license_revocation: Optional[bool] = None
    has_pending_regulatory_proceeding: Optional[bool] = None
    has_court_injunction: Optional[bool] = None
    has_court_investment_statute_violation: Optional[bool] = None
    has_settled_investment_civil_action: Optional[bool] = None
    has_pending_civil_proceeding: Optional[bool] = None
    felony_conviction_count: Optional[int] = None
    felony_charge_count: Optional[int] = None
    misdemeanor_investment_or_fraud_conviction_count: Optional[int] = None
    misdemeanor_investment_or_fraud_charge_count: Optional[int] = None
    sec_cftc_false_statement_count: Optional[int] = None
    sec_cftc_violation_count: Optional[int] = None
    sec_cftc_authorization_restriction_cause_count: Optional[int] = None
    sec_cftc_investment_order_count: Optional[int] = None
    sec_cftc_penalty_or_cease_desist_count: Optional[int] = None
    other_regulator_false_statement_count: Optional[int] = None
    other_regulator_violation_count: Optional[int] = None
    other_regulator_authorization_restriction_cause_count: Optional[int] = None
    other_regulator_investment_order_count: Optional[int] = None
    other_regulator_registration_or_association_restriction_count: Optional[int] = None
    sro_false_statement_count: Optional[int] = None
    sro_rule_violation_count: Optional[int] = None
    sro_authorization_restriction_cause_count: Optional[int] = None
    sro_discipline_count: Optional[int] = None
    professional_license_revocation_count: Optional[int] = None
    pending_regulatory_proceeding_count: Optional[int] = None
    court_injunction_count: Optional[int] = None
    court_investment_statute_violation_count: Optional[int] = None
    settled_investment_civil_action_count: Optional[int] = None
    pending_civil_proceeding_count: Optional[int] = None
    ia_affiliate_count: Optional[int] = None
    ia_bd_affiliate_count: Optional[int] = None
    bd_affiliate_count: Optional[int] = None
    acquired_firm_sec_number: Optional[str] = None
    dataset_version: str
    created_timestamp: datetime
    source_dataset: str
    record_hash: str
    last_seen_version: str
    current_status: str

    @validator(
        "sec_number", "cik_number", "additional_crd_numbers", "primary_business_name",
        "sec_region", "website_address", "firm_type", "sec_current_status",
        "form_version", "acquired_firm_sec_number", "other_client_type_description",
        "organization_type", "organization_type_other", "organization_state", "organization_country", pre=True
    )
    def parse_optional_str(cls, v):
        if isinstance(v, float) and v != v:  # Check for NaN
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @validator(
        "umbrella_registration", "has_unlisted_control_person", "has_related_person_control",
        "under_common_control", "shares_supervised_persons", "shares_location",
        "has_item_11_disclosure", "has_felony_conviction", "has_felony_charge",
        "has_misdemeanor_investment_or_fraud_conviction", "has_misdemeanor_investment_or_fraud_charge",
        "has_sec_cftc_false_statement", "has_sec_cftc_violation",
        "has_sec_cftc_authorization_restriction_cause", "has_sec_cftc_investment_order",
        "has_sec_cftc_penalty_or_cease_desist", "has_other_regulator_false_statement",
        "has_other_regulator_violation", "has_other_regulator_authorization_restriction_cause",
        "has_other_regulator_investment_order", "has_other_regulator_registration_or_association_restriction",
        "has_sro_false_statement", "has_sro_rule_violation", "has_sro_authorization_restriction_cause",
        "has_sro_discipline", "has_professional_license_revocation", "has_pending_regulatory_proceeding",
        "has_court_injunction", "has_court_investment_statute_violation",
        "has_settled_investment_civil_action", "has_pending_civil_proceeding", pre=True
    )
    def parse_bool(cls, v):
        if isinstance(v, float) and v != v: return None # Check for NaN
        if v is None: return None
        if isinstance(v, str):
            s = v.strip().upper()
            if s == 'Y': return True
            if s == 'N': return False
            if s == '': return None
        if isinstance(v, bool): return v
        return None

    @validator(
        "total_aum", "discretionary_aum", "non_discretionary_aum", "other_regulatory_aum",
        "individual_client_aum", "hnw_client_aum", "banking_client_aum",
        "investment_company_client_aum", "business_development_company_client_aum",
        "pooled_investment_vehicle_client_aum", "pension_profit_sharing_client_aum",
        "charitable_organization_client_aum", "state_municipal_entity_client_aum",
        "other_investment_adviser_client_aum", "insurance_company_client_aum",
        "sovereign_wealth_fund_client_aum", "corporation_other_business_client_aum",
        "other_client_aum", "individual_hnw_client_aum", pre=True
    )
    def parse_money(cls, v):
        if isinstance(v, float) and v != v: return None # Check for NaN
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        if isinstance(v, str): v = v.replace(',', '').strip()
        try: return Decimal(v)
        except Exception: return None

    @validator(
        "total_relying_advisers", "total_additional_crd_numbers", "total_cik_numbers",
        "total_website_addresses", "total_books_and_records_locations", "private_fund_count",
        "discretionary_account_count", "non_discretionary_account_count", "total_account_count",
        "individual_client_count", "hnw_client_count", "banking_client_count",
        "investment_company_client_count", "business_development_company_client_count",
        "pooled_investment_vehicle_client_count", "pension_profit_sharing_client_count",
        "charitable_organization_client_count", "state_municipal_entity_client_count",
        "other_investment_adviser_client_count", "insurance_company_client_count",
        "sovereign_wealth_fund_client_count", "corporation_other_business_client_count",
        "other_client_count", "individual_hnw_client_count",
        "employee_count", "advisory_employee_count", "broker_dealer_rep_count",
        "state_iar_count", "other_adviser_iar_count", "insurance_agent_count",
        "solicitor_count",
        "hedge_fund_count", "pe_fund_count", "real_estate_fund_count", "vc_fund_count",
        "liquidity_fund_count", "disciplinary_event_count", "civil_action_count",
        "bonding_requirement_count", "other_regulatory_event_count",
        "financial_condition_event_count", "affiliation_change_count",
        "public_company_control_person_count", "ia_affiliate_count",
        "ia_bd_affiliate_count", "bd_affiliate_count", "felony_conviction_count",
        "felony_charge_count", "misdemeanor_investment_or_fraud_conviction_count",
        "misdemeanor_investment_or_fraud_charge_count", "sec_cftc_false_statement_count",
        "sec_cftc_violation_count", "sec_cftc_authorization_restriction_cause_count",
        "sec_cftc_investment_order_count", "sec_cftc_penalty_or_cease_desist_count",
        "other_regulator_false_statement_count", "other_regulator_violation_count",
        "other_regulator_authorization_restriction_cause_count", "other_regulator_investment_order_count",
        "other_regulator_registration_or_association_restriction_count", "sro_false_statement_count",
        "sro_rule_violation_count", "sro_authorization_restriction_cause_count", "sro_discipline_count",
        "professional_license_revocation_count", "pending_regulatory_proceeding_count",
        "court_injunction_count", "court_investment_statute_violation_count",
        "settled_investment_civil_action_count", "pending_civil_proceeding_count", pre=True
    )
    def parse_int(cls, v):
        if isinstance(v, float) and v != v: return None # Check for NaN
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        try: return int(str(v).replace(',', '').strip())
        except ValueError: return None

    @validator(
        "individual_client_fewer_than_five", "hnw_client_fewer_than_five",
        "banking_client_fewer_than_five", "pooled_investment_vehicle_client_fewer_than_five",
        "pension_profit_sharing_client_fewer_than_five",
        "charitable_organization_client_fewer_than_five",
        "state_municipal_entity_client_fewer_than_five",
        "other_investment_adviser_client_fewer_than_five",
        "insurance_company_client_fewer_than_five",
        "sovereign_wealth_fund_client_fewer_than_five",
        "corporation_other_business_client_fewer_than_five",
        "other_client_fewer_than_five", pre=True
    )
    def parse_fewer_than_five(cls, v):
        if isinstance(v, float) and v != v: return None
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        return str(v).strip().lower() == "fewer than 5 clients"

    @validator(
        "provides_financial_planning", "advises_individuals_or_small_businesses",
        "advises_investment_companies", "advises_pooled_investment_vehicles",
        "advises_institutional_clients", "provides_pension_consulting",
        "selects_other_advisers", "publishes_periodicals_or_newsletters",
        "provides_security_ratings_or_pricing", "provides_market_timing",
        "provides_educational_seminars_or_workshops", "provides_other_advisory_services",
        "succession_indicator", pre=True
    )
    def parse_indicator(cls, v):
        if isinstance(v, float) and v != v: return None
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        if isinstance(v, bool): return v
        value = str(v).strip().upper()
        if value == 'Y': return True
        if value == 'N': return False
        return None

    @validator(
        "sec_status_effective_date", "latest_adv_filing_date",
        "jurisdiction_notice_filed_effective_date", "succession_date", pre=True
    )
    def parse_date(cls, v):
        if isinstance(v, float) and v != v: return None # Check for NaN
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        if isinstance(v, datetime): return v
        try: return datetime.strptime(str(v).strip(), "%m/%d/%Y")
        except ValueError: return None


class FirmOffice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firm_id: str
    office_type: OfficeType
    street_address_1: Optional[str] = None
    street_address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    is_private_residence: Optional[bool] = None
    telephone: Optional[str] = None
    facsimile: Optional[str] = None
    dataset_version: str
    created_timestamp: datetime
    source_dataset: str
    record_hash: str
    last_seen_version: str
    current_status: str

    @validator(
        "street_address_1", "street_address_2", "city", "state", "country",
        "postal_code", "telephone", "facsimile", pre=True
    )
    def parse_optional_str(cls, v):
        if isinstance(v, float) and v != v:  # Check for NaN
            return None
        return v

    @validator("is_private_residence", pre=True)
    def parse_bool(cls, v):
        if isinstance(v, float) and v != v: return None # Check for NaN
        if v is None: return None
        if isinstance(v, str):
            s = v.strip().upper()
            if s == 'Y': return True
            if s == 'N': return False
            if s == '': return None
        return None


class FirmAcquiredFirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_firm_id: str
    acquired_name: Optional[str] = None
    acquired_sec_number: Optional[str] = None
    acquired_crd_number: Optional[str] = None
    dataset_version: str
    created_timestamp: datetime
    source_dataset: str
    record_hash: str
    last_seen_version: str
    current_status: str

    @validator("acquired_name", "acquired_sec_number", "acquired_crd_number", pre=True)
    def parse_optional_str(cls, v):
        if isinstance(v, float) and v != v:  # Check for NaN
            return None
        return v
