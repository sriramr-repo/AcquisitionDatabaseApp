# Canonical Data Model — Mapping Specification

Source: `bronze_raw_IA_SEC___FIRM_ROSTER_FOIA_DOWNLOAD___34622660_ia07012026`
Dataset version: `ia07012026`

## Legend
- **T**: `identity` — direct copy
- **T**: `parse_bool` — 'Y'/'N'/empty → True/False/None
- **T**: `parse_money` — `'628,902,725.00'` → Decimal
- **T**: `parse_int` — whitespace-padded count → int
- **T**: `parse_date` — `'MM/DD/YYYY'` → ISO date
- **T**: derived — roll-up/summary

---

## Entity: `Firm`

| Destination Field | Source Column | Transformation | Notes |
|---|---|---|---|
| firm_id | Organization CRD# | identity | Natural key |
| sec_number | SEC# | identity | |
| cik_number | CIK# | identity | |
| legal_name | Legal Name | identity | |
| primary_business_name | Primary Business Name | identity | |
| website | Website Address | identity | |
| sec_region | SEC Region | identity | |
| umbrella_flag | Umbrella Registration | parse_bool | |
| current_status | SEC Current Status | identity (enum) | |
| status_effective_date | SEC Status Effective Date | parse_date | |
| jurisdiction_notice_date | Jurisdiction Notice Filed-Effective Date | parse_date | |
| latest_filing_date | Latest ADV Filing Date | parse_date | |
| form_version | Form Version | identity | |
| total_relying_advisers | Total number of relying advisers | parse_int | |
| total_additional_crd_numbers | Total number of additional CRD numbers | parse_int | |
| total_cik_numbers | Total number of CIK numbers | parse_int | |
| total_website_addresses | Total Number of Website Addresses | parse_int | |
| total_books_and_records_locations | Total Number of Books and Records Locations | parse_int | |
| total_aum | 5F(3) | parse_money | |
| discretionary_aum | 5F(2)(a) | parse_money | |
| non_discretionary_aum | 5F(2)(b) | parse_money | |
| other_regulatory_aum | 5F(2)(c) | parse_money | |
| midyear_discretionary_pct | 5.K.(1)(a)(iv) midyear percentage | parse_int → float | |
| year_end_discretionary_pct | 5.K.(1)(a)(iv) end year percentage | parse_int → float | |
| private_fund_count | Count of Private Funds - 7B(1) | parse_int | |
| has_hedge_funds | Any Hedge Funds | parse_bool | |
| hedge_fund_count | Total number of Hedge funds | parse_int | |
| has_pe_funds | Any PE Funds | parse_bool | |
| pe_fund_count | Total number of PE funds | parse_int | |
| has_real_estate_funds | Any Real Estate Funds | parse_bool | |
| real_estate_fund_count | Total number of Real Estate funds | parse_int | |
| has_vc_funds | Any VC Funds | parse_bool | |
| vc_fund_count | Total number of VC funds | parse_int | |
| has_liquidity_funds | Any Liquidity Funds | parse_bool | |
| liquidity_fund_count | Total number of Liquidity funds | parse_int | |
| total_gross_assets_private_funds | Total Gross Assets of Private Funds | parse_money | |
| has_disciplinary_events | 11A(1) | parse_bool | |
| disciplinary_event_count | Count of 11A(1) disclosures | parse_int | |
| has_civil_actions | 11A(2) | parse_bool | |
| civil_action_count | Count of 11A(2) disclosures | parse_int | |
| has_bonding_requirements | 11C(1) | parse_bool | |
| bonding_requirement_count | Count of 11C(1) disclosures | parse_int | |
| has_other_regulatory_events | 11D(1) | parse_bool | |
| other_regulatory_event_count | Count of 11D(1) disclosures | parse_int | |
| has_financial_condition_events | 11F | parse_bool | |
| financial_condition_event_count | Count of 11F disclosures | parse_int | |
| has_affiliation_changes | 11G | parse_bool | |
| affiliation_change_count | Count of 11G disclosures | parse_int | |
| has_custody_arrangements | 9A(1) | parse_bool | |
| total_custody_amount | Total Custody Amount | parse_money | |
| has_unqualified_opinion | 9C Unqual Opinion | parse_bool | |
| has_audit_requirements | 9E | parse_bool | |
| under_common_control | Under Common Control | parse_bool | |
| share_supervised_persons | Share Supervised Persons | parse_bool | |
| share_location | Share Location | parse_bool | |
| public_company_control_person_count | Count of Control person Public Reporting Company | parse_int | |
| ia_affiliate_count | Count of IA Affiliates | parse_int | |
| ia_bd_affiliate_count | Count of IA/BD Affiliates | parse_int | |
| bd_affiliate_count | Count of BD Affiliates | parse_int | |
| dataset_version | — (pipeline param) | identity | Lineage |
| created_timestamp | — (now()) | identity | Lineage |
| source_record_hash | (entire source row) | sha256(json(row)) | Lineage |
| last_seen_version | — (current dataset_version) | identity | Lineage |
| current_status_flag | 'active' | identity | Lineage |

---

## Entity: `FirmOffice`

| Destination Field | Source Column (Main) | Source Column (Mail) | Source Column (Books&Records) | Transformation |
|---|---|---|---|---|
| firm_id | Organization CRD# | Organization CRD# | Organization CRD# | identity |
| office_type | `main` (const) | `mail` (const) | `books_records` (const) | derived |
| street_address_1 | Main Office Street Address 1 | Mail Office Street Address 1 | Location of Books and Records Street Address 1 | identity |
| street_address_2 | Main Office Street Address 2 | Mail Office Street Address 2 | Location of Books and Records Street Address 2 | identity |
| city | Main Office City | Mail Office City | Location of Books and Records City | identity |
| state | Main Office State | Mail Office State | Location of Books and Records State | identity |
| country | Main Office Country | Mail Office Country | Location of Books and Records Country | identity |
| postal_code | Main Office Postal Code | Mail Office Postal Code | Location of Books and Records Postal Code | identity |
| is_private_residence | Main Office Private Residence Flag | Mail Office Private Residence Flag | Location of Books and Records Private Residence Flag | parse_bool |
| telephone | Main Office Telephone Number | — | — | identity |
| facsimile | Main Office Facsimile Number | — | — | identity |

---

## Entity: `FirmAcquiredFirm`

| Destination Field | Source Column | Transformation |
|---|---|---|
| parent_firm_id | Organization CRD# | identity |
| acquired_name | Acquired Firm | identity |
| acquired_sec_number | Acquired Firm SEC# | identity |
| acquired_crd_number | Acquired Firm CRD# | identity |

---

## Transformation Functions

| Name | Input → Output | Example |
|---|---|---|
| identity | str → str | `'801-13057'` → `'801-13057'` |
| parse_bool | str → bool/None | `'Y'` → `True`, `'N'` → `False`, `''` → `None` |
| parse_money | str → Decimal/None | `' 628,902,725.00'` → `628902725.00` |
| parse_int | str → int/None | `'   0'` → `0`, `''` → `None` |
| parse_date | str → date/None | `'01/01/2024'` → `2024-01-01` |
| sha256 | dict → str | `sha256(json.dumps(row, sort_keys=True))` |