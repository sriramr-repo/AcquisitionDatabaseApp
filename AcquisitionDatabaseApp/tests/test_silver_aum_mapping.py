import json
from decimal import Decimal

import pandas as pd

from src.normalizer import Normalizer


def make_source_row(**overrides):
    with open("data/mapping_specification.json") as mapping_file:
        mappings = json.load(mapping_file)["entities"]["Firm"]["mappings"]

    row = {source: None for source in mappings.values() if source}
    row.update(
        {
            "Organization CRD#": "12345",
            "Legal Name": "Example RIA",
            "5.G.(3) - Total amount of Parallel Assets": "999999999999",
        }
    )
    row.update(overrides)
    return row


def normalize_one(row):
    normalized = Normalizer("fixture").normalize_batch(pd.DataFrame([row]))
    assert len(normalized["firms"]) == 1
    return normalized["firms"][0]


def test_aum_and_account_fields_use_5f_source_columns():
    firm = normalize_one(
        make_source_row(
            **{
                "5F(2)(a)": " 750,000.00",
                "5F(2)(b)": "250,000.00",
                "5F(2)(c)": " 1,000,000.00",
                "5F(2)(d)": " 1,234",
                "5F(2)(e)": "56",
                "5F(2)(f)": "1,290",
            }
        )
    )

    assert firm.discretionary_aum == Decimal("750000.00")
    assert firm.non_discretionary_aum == Decimal("250000.00")
    assert firm.total_aum == Decimal("1000000.00")
    assert firm.discretionary_account_count == 1234
    assert firm.non_discretionary_account_count == 56
    assert firm.total_account_count == 1290
    assert firm.total_aum != Decimal("999999999999")


def test_blank_and_null_aum_and_account_values_remain_none():
    firm = normalize_one(
        make_source_row(
            **{
                "5F(2)(a)": "",
                "5F(2)(b)": None,
                "5F(2)(c)": "",
                "5F(2)(d)": "",
                "5F(2)(e)": None,
                "5F(2)(f)": "",
            }
        )
    )

    assert firm.discretionary_aum is None
    assert firm.non_discretionary_aum is None
    assert firm.total_aum is None
    assert firm.discretionary_account_count is None
    assert firm.non_discretionary_account_count is None
    assert firm.total_account_count is None
