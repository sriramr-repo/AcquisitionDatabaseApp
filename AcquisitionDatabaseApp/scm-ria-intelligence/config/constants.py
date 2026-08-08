"\"\"\"Project-wide constants and enumerations.\"\"\"

from enum import Enum, IntEnum


class DataSource(Enum):
    \"\"\"Data source enumerations.\"\"\"
    SEC_FORM_ADV = "sec_form_adv"
    SEC_IAPD = "sec_iapd"
    FINRA_BROKERCHECK = "finra_brokercheck"
    MANUAL_ENTRY = "manual_entry"


class FirmStatus(Enum):
    \"\"\"RIA firm status enumerations.\"\"\"
    ACTIVE = "active"
    INACTIVE = "inactive"
    TERMINATED = "terminated"
    MERGED = "merged"
    ACQUIRED = "acquired"
    UNKNOWN = "unknown"


class OpportunityType(Enum):
    \"\"\"Acquisition opportunity type enumerations.\"\"\"
    ACQUISITION = "acquisition"
    MERGER = "merger"
    SUCCESSION = "succession"
    EMPLOYMENT = "employment"
    STRATEGIC_PARTNERSHIP = "strategic_partnership"
    SUB_ADVISORY = "sub_advisory"


class ScoringCategory(IntEnum):
    \"\"\"Scoring category weight enumerations.\"\"\"
    ASSETS_UNDER_MANAGEMENT = 25
    CLIENT_BASE = 20
    GEOGRAPHIC_FIT = 15
    SERVICE_OFFERINGS = 15
    FEE_STRUCTURE = 10
    REGULATORY_HISTORY = 10
    GROWTH_POTENTIAL = 5


class ReportFormat(Enum):
    \"\"\"Report format enumerations.\"\"\"
    EXCEL = "xlsx"
    CSV = "csv"
    PDF = "pdf"
    JSON = "json"


# File patterns
SEC_ADV_FILE_PATTERN = "adv_*.txt"
SEC_IAPD_FILE_PATTERN = "iapd_*.csv"

# Database constants
DEFAULT_BATCH_SIZE = 1000
MAX_RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5

# Scoring constants
MAX_SCORE = 100
MIN_SCORE = 0

# Date formats
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Path constants
RAW_DATA_DIR = "data/raw/"
PROCESSED_DATA_DIR = "data/processed/"
EXPORT_DIR = "data/exports/"
TEMPLATE_DIR = "config/templates/"

# HTTP constants
DEFAULT_USER_AGENT = "SCM-RIA-Intelligence-Platform/0.1.0 (+https://standishcapital.com)"
REQUEST_TIMEOUT = 30
MAX_REDIRECTS = 5

# Validation constants
MIN_CRD_NUMBER = 1000
MAX_CRD_NUMBER = 999999
VALID_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI"
}
"