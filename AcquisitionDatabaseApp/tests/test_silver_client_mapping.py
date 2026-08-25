import json
from decimal import Decimal

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


def test_individual_and_hnw_fields_and_derived_totals():
    firm = normalize_one(
        make_source_row(
            **{
                "5D(a)(1)": " 12",
                "5D(a)(2)": "",
                "5D(a)(3)": " 1,200,000.00",
                "5D(b)(1)": "3",
                "5D(b)(2)": "Fewer than 5 clients",
                "5D(b)(3)": "800,000.00",
            }
        )
    )

    assert firm.individual_client_count == 12
    assert firm.individual_client_fewer_than_five is None
    assert firm.individual_client_aum == Decimal("1200000.00")
    assert firm.hnw_client_count == 3
    assert firm.hnw_client_fewer_than_five is True
    assert firm.hnw_client_aum == Decimal("800000.00")
    assert firm.individual_hnw_client_count == 15
    assert firm.individual_hnw_client_aum == Decimal("2000000.00")


def test_major_client_categories_map_without_collapsing_null_or_zero():
    firm = normalize_one(
        make_source_row(
            **{
                "5D(c)(1)": "0",
                "5D(c)(2)": "",
                "5D(c)(3)": "0.00",
                "5D(d)(1)": "7",
                "5D(d)(3)": "2,500,000.00",
                "5D(f)(1)": "4",
                "5D(f)(3)": "3,000,000.00",
                "5D(n)(1)": "",
                "5D(n)(2)": None,
                "5D(n)(3)": "",
                "5D(n)(3) - Other": "Associations",
            }
        )
    )

    assert firm.banking_client_count == 0
    assert firm.banking_client_fewer_than_five is None
    assert firm.banking_client_aum == Decimal("0.00")
    assert firm.investment_company_client_count == 7
    assert firm.investment_company_client_aum == Decimal("2500000.00")
    assert firm.pooled_investment_vehicle_client_count == 4
    assert firm.pooled_investment_vehicle_client_aum == Decimal("3000000.00")
    assert firm.other_client_count is None
    assert firm.other_client_fewer_than_five is None
    assert firm.other_client_aum is None
    assert firm.other_client_type_description == "Associations"
