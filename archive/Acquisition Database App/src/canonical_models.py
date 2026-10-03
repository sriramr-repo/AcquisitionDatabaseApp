        # ponytail: add more robust boolean parsing if other values appear. ceiling: 'Y'/'N' or empty.
        # add when: encounter other boolean representations.
        raise ValueError(f"Invalid boolean flag: {v}")

    @validator("total_aum", "discretionary_aum", "non_discretionary_aum", "other_regulatory_aum", pre=True)
    def parse_money(cls, v: Any) -> Optional[Decimal]:
        """Parses currency strings like '628,902,725.00' to Decimal."""
        if v is None or (isinstance(v, str) and v.strip() == ''):
            return None
        if isinstance(v, str):
            v = v.replace(',', '').strip()
        try:
            return Decimal(v)
        except Exception:
            return None

    @validator(
        "total_relying_advisers",
        "total_additional_crd_numbers",
        "total_cik_numbers",
        "total_website_addresses",
        "total_books_and_records_locations",
        "private_fund_count",
        "hedge_fund_count",
        "pe_fund_count",
        "real_estate_fund_count",
        "vc_fund_count",
        "liquidity_fund_count",
        "disciplinary_event_count",
        "civil_action_count",
        "bonding_requirement_count",
        "other_regulatory_event_count",
        "financial_condition_event_count",
        "affiliation_change_count",
        "public_company_control_person_count",
        "ia_affiliate_count",
        "ia_bd_affiliate_count",
        "bd_affiliate_count",
        pre=True,
    )
    def parse_int(cls, v: Any) -> Optional[int]:
        """Parses whitespace-padded count strings to int."""
        if v is None or (isinstance(v, str) and v.strip() == ''):
            return None
        try:
            return int(str(v).strip())
        except ValueError:
            return None


class FirmOffice(BaseModel):
    """Firm office location.

    Stores different office types (Main, Mail, Books/Records).
    """

    model_config = ConfigDict(extra="forbid")

    firm_id: str = Field(..., description="Foreign key to Firm.")
    office_type: OfficeType = Field(..., description="Type of the office.")
    street_address_1: Optional[str] = Field(None, alias="Main Office Street Address 1")
    street_address_2: Optional[str] = Field(None, alias="Main Office Street Address 2")
    city: Optional[str] = Field(None, alias="Main Office City")
    state: Optional[str] = Field(None, alias="Main Office State")
    country: Optional[str] = Field(None, alias="Main Office Country")
    postal_code: Optional[str] = Field(None, alias="Main Office Postal Code")
    is_private_residence: Optional[bool] = Field(None, alias="Main Office Private Residence Flag")
    telephone: Optional[str] = Field(None, alias="Main Office Telephone Number")
    facsimile: Optional[str] = Field(None, alias="Main Office Facsimile Number")


class FirmAcquiredFirm(BaseModel):
    """Details of firms acquired by the parent Firm."""

    model_config = ConfigDict(extra="forbid")

    parent_firm_id: str = Field(..., description="Foreign key to parent Firm.")
    acquired_name: Optional[str] = Field(None, alias="Acquired Firm")
    acquired_sec_number: Optional[str] = Field(None, alias="Acquired Firm SEC#")
    acquired_crd_number: Optional[str] = Field(None, alias="Acquired Firm CRD#")