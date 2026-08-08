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
        "form_version", "acquired_firm_sec_number", pre=True
    )
    def parse_optional_str(cls, v):
        if isinstance(v, float) and v != v:  # Check for NaN
            return None
        return v

    @validator("umbrella_registration", pre=True)
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

    @validator("total_aum", "discretionary_aum", "non_discretionary_aum", "other_regulatory_aum", pre=True)
    def parse_money(cls, v):
        if isinstance(v, float) and v != v: return None # Check for NaN
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        if isinstance(v, str): v = v.replace(',', '').strip()
        try: return Decimal(v)
        except Exception: return None

    @validator(
        "total_relying_advisers", "total_additional_crd_numbers", "total_cik_numbers",
        "total_website_addresses", "total_books_and_records_locations", "private_fund_count",
        "hedge_fund_count", "pe_fund_count", "real_estate_fund_count", "vc_fund_count",
        "liquidity_fund_count", "disciplinary_event_count", "civil_action_count",
        "bonding_requirement_count", "other_regulatory_event_count",
        "financial_condition_event_count", "affiliation_change_count",
        "public_company_control_person_count", "ia_affiliate_count",
        "ia_bd_affiliate_count", "bd_affiliate_count", pre=True
    )
    def parse_int(cls, v):
        if isinstance(v, float) and v != v: return None # Check for NaN
        if v is None or (isinstance(v, str) and v.strip() == ''): return None
        try: return int(str(v).strip())
        except ValueError: return None

    @validator(
        "sec_status_effective_date", "latest_adv_filing_date",
        "jurisdiction_notice_filed_effective_date", pre=True
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
