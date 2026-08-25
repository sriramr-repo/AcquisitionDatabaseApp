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


def test_item_5a_and_5b_staffing_fields_map_and_parse_counts():
    firm = normalize_one(
        make_source_row(
            **{
                "5A": " 1,000",
                "5B(1)": "750",
                "5B(2)": "25",
                "5B(3)": "500",
                "5B(4)": "10",
                "5B(5)": " 5 ",
                "5B(6)": "2",
            }
        )
    )

    assert firm.employee_count == 1000
    assert firm.advisory_employee_count == 750
    assert firm.broker_dealer_rep_count == 25
    assert firm.state_iar_count == 500
    assert firm.other_adviser_iar_count == 10
    assert firm.insurance_agent_count == 5
    assert firm.solicitor_count == 2


def test_blank_and_zero_staffing_values_preserve_null_zero_distinction():
    firm = normalize_one(
        make_source_row(
            **{
                "5A": "",
                "5B(1)": None,
                "5B(2)": "0",
                "5B(3)": "",
                "5B(4)": None,
                "5B(5)": "0",
                "5B(6)": "",
            }
        )
    )

    assert firm.employee_count is None
    assert firm.advisory_employee_count is None
    assert firm.broker_dealer_rep_count == 0
    assert firm.state_iar_count is None
    assert firm.other_adviser_iar_count is None
    assert firm.insurance_agent_count == 0
    assert firm.solicitor_count is None
