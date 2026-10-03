"\"\"\"Data schemas for RIA entities and relationships.\"\"\"

from typing import Optional, List, Dict, Any
from datetime import date, datetime
from dataclasses import dataclass, field

from config.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Address:
    \"\"\"Physical address schema.\"\"\"
    street: str
    city: str
    state: str
    zip_code: str
    country: str = "US"
    address_type: str = "business"  # business, mailing, residential
    

@dataclass
class Contact:
    \"\"\"Contact information schema.\"\"\"
    name: str
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_extension: Optional[str] = None
    

@dataclass
class RIABasicInfo:
    \"\"\"Basic RIA firm information schema.\"\"\"
    crd_number: int
    legal_name: str
    doing_business_as: Optional[str] = None
    sec_file_number: Optional[str] = None
    status: str = "active"
    registration_date: Optional[date] = None
    

@dataclass
class RIAFinancials:
    \"\"\"RIA financial information schema.\"\"\"
    crd_number: int
    assets_under_management: Optional[float] = None
    discretionary_aum: Optional[float] = None
    non_discretionary_aum: Optional[float] = None
    total_clients: Optional[int] = None
    high_net_worth_clients: Optional[int] = None
    pension_plan_clients: Optional[int] = None
    other_clients: Optional[int] = None
    reporting_date: Optional[date] = None
    

@dataclass
class RIAServices:
    \"\"\"RIA service offerings schema.\"\"\"
    crd_number: int
    portfolio_management: bool = False
    financial_planning: bool = False
    pension_consulting: bool = False
    selection_of_advisors: bool = False
    publication_of_periodicals: bool = False
    security_ratings: bool = False
    market_timing: bool = False
    educational_seminars: bool = False
    other_services: List[str] = field(default_factory=list)
    

@dataclass
class RIAFees:
    \"\"\"RIA fee structure schema.\"\"\"
    crd_number: int
    percentage_of_aum: Optional[float] = None
    hourly_charges: Optional[float] = None
    subscription_fees: Optional[float] = None
    fixed_fees: Optional[float] = None
    commission_based: bool = False
    performance_based: bool = False
    other_fee_arrangements: List[str] = field(default_factory=list)
    

@dataclass
class RIAAdvisor:
    \"\"\"Individual advisor schema.\"\"\"
    crd_number: int
    advisor_crd: int
    name: str
    title: Optional[str] = None
    start_date: Optional[date] = None
    status: str = "active"
    

@dataclass
class RIAFirm:
    \"\"\"Complete RIA firm schema combining all data.\"\"\"
    basic_info: RIABasicInfo
    addresses: List[Address] = field(default_factory=list)
    contacts: List[Contact] = field(default_factory=list)
    financials: Optional[RIAFinancials] = None
    services: Optional[RIAServices] = None
    fees: Optional[RIAFees] = None
    advisors: List[RIAAdvisor] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        \"\"\"Convert RIAFirm to dictionary representation.\"\"\"
        return {
            "basic_info": self.basic_info.__dict__,
            "financials": self.financials.__dict__ if self.financials else None,
            "services": self.services.__dict__ if self.services else None,
            "fees": self.fees.__dict__ if self.fees else None,
        }


@dataclass
class AcquisitionScore:
    \"\"\"Acquisition scoring schema.\"\"\"
    crd_number: int
    overall_score: float
    category_scores: Dict[str, float]  # category -> score
    last_updated: datetime
    scoring_version: str
    notes: Optional[str] = None
    

@dataclass
class AcquisitionCandidate:
    \"\"\"Acquisition candidate schema.\"\"\"
    firm: RIAFirm
    score: AcquisitionScore
    opportunity_type: str
    priority: str  # high, medium, low
    research_status: str  # pending, in_progress, completed
    notes: Optional[str] = None
    created_date: datetime = field(default_factory=datetime.now)
    updated_date: datetime = field(default_factory=datetime.now)"