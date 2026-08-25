import json

import pandas as pd

from src.normalizer import Normalizer


def make_source_row(**overrides):
    with open("data/mapping_specification.json") as mapping_file:
        mappings = json.load(mapping_file)["entities"]["Firm"]["mappings"]
    row = {source: None for source in mappings.values() if source}
    row.update({"Organization CRD#": "12345", "Legal Name": "Example RIA"})
    row.update(overrides)
    return row


def normalize_one(row):
    normalized = Normalizer("fixture").normalize_batch(pd.DataFrame([row]))
    assert len(normalized["firms"]) == 1
    return normalized["firms"][0]


def test_organization_and_control_proxy_fields_map_with_sec_types():
    firm = normalize_one(
        make_source_row(
            **{
                "3A": "Limited Liability Company",
                "3A-Other": "",
                "3C-State": "NY",
                "3C-Country": "United States",
                "10A": "Y",
                "Control/Controlled by Related Person": "N",
                "Under Common Control": "Y",
                "Share Supervised Persons": "N",
                "Share Location": "Y",
                "Count of Control person Public Reporting Company": "2",
            }
        )
    )

    assert firm.organization_type == "Limited Liability Company"
    assert firm.organization_type_other is None
    assert firm.organization_state == "NY"
    assert firm.organization_country == "United States"
    assert firm.has_unlisted_control_person is True
    assert firm.has_related_person_control is False
    assert firm.under_common_control is True
    assert firm.shares_supervised_persons is False
    assert firm.shares_location is True
    assert firm.public_company_control_person_count == 2


def test_all_item_11_counts_map_and_preserve_zero_null_and_commas():
    values = {
        "11": "Y",
        "11A(1)": "Y",
        "11A(2)": "Y",
        "11B(2)": "Y",
        "11G": "Y",
        "11H(2)": "Y",
        "Count of 11A(1) disclosures": "1,000",
        "Count of 11A(2) disclosures": "0",
        "Count of 11B(1) disclosures": "2",
        "Count of 11B(2) disclosures": "",
        "Count of 11C(1) disclosures": "3",
        "Count of 11C(2) disclosures": "4",
        "Count of 11C(3) disclosures": "5",
        "Count of 11C(4) disclosures": "6",
        "Count of 11C(5) disclosures": "7",
        "Count of 11D(1) disclosures": "8",
        "Count of 11D(2) disclosures": "9",
        "Count of 11D(3) disclosures": "10",
        "Count of 11D(4) disclosures": "11",
        "Count of 11D(5) disclosures": "12",
        "Count of 11E(1) disclosures": "13",
        "Count of 11E(2) disclosures": "14",
        "Count of 11E(3) disclosures": "15",
        "Count of 11E(4) disclosures": "16",
        "Count of 11F disclosures": "17",
        "Count of 11G disclosures": "18",
        "Count of 11H(1)(a) disclosures": "19",
        "Count of 11H(1)(b) disclosures": "20",
        "Count of 11H(1)(c) disclosures": "21",
        "Count of 11H(2) disclosures": "22",
    }
    firm = normalize_one(make_source_row(**values))

    assert firm.has_item_11_disclosure is True
    assert firm.has_felony_conviction is True
    assert firm.has_felony_charge is True
    assert firm.has_misdemeanor_investment_or_fraud_charge is True
    assert firm.has_pending_regulatory_proceeding is True
    assert firm.has_pending_civil_proceeding is True
    assert firm.felony_conviction_count == 1000
    assert firm.felony_charge_count == 0
    assert firm.misdemeanor_investment_or_fraud_conviction_count == 2
    assert firm.misdemeanor_investment_or_fraud_charge_count is None
    assert firm.sec_cftc_false_statement_count == 3
    assert firm.sec_cftc_penalty_or_cease_desist_count == 7
    assert firm.other_regulator_registration_or_association_restriction_count == 12
    assert firm.sro_discipline_count == 16
    assert firm.professional_license_revocation_count == 17
    assert firm.pending_regulatory_proceeding_count == 18
    assert firm.court_injunction_count == 19
    assert firm.pending_civil_proceeding_count == 22


def test_existing_aum_client_advisory_and_staffing_mappings_remain_intact():
    firm = normalize_one(
        make_source_row(
            **{
                "5F(2)(c)": "20,000,000",
                "5D(a)(1)": "10",
                "5D(b)(1)": "2",
                "5G(2)": "Y",
                "5A": "4",
                "5B(1)": "3",
            }
        )
    )

    assert firm.total_aum == 20000000
    assert firm.individual_client_count == 10
    assert firm.hnw_client_count == 2
    assert firm.individual_hnw_client_count == 12
    assert firm.advises_individuals_or_small_businesses is True
    assert firm.employee_count == 4
    assert firm.advisory_employee_count == 3
