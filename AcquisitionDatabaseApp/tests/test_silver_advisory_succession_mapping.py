import json
from datetime import datetime

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


def test_item_5g_advisory_activities_and_succession_map():
    firm = normalize_one(
        make_source_row(
            **{
                "5G(1)": "Y",
                "5G(2)": "N",
                "5G(3)": "Y",
                "5G(4)": "N",
                "5G(5)": "Y",
                "5G(6)": "N",
                "5G(7)": "Y",
                "5G(8)": "N",
                "5G(9)": "Y",
                "5G(10)": "N",
                "5G(11)": "Y",
                "5G(12)": "N",
                "4A": "Y",
                "4B": "04/22/2026",
            }
        )
    )

    assert firm.provides_financial_planning is True
    assert firm.advises_individuals_or_small_businesses is False
    assert firm.advises_investment_companies is True
    assert firm.advises_pooled_investment_vehicles is False
    assert firm.advises_institutional_clients is True
    assert firm.provides_pension_consulting is False
    assert firm.selects_other_advisers is True
    assert firm.publishes_periodicals_or_newsletters is False
    assert firm.provides_security_ratings_or_pricing is True
    assert firm.provides_market_timing is False
    assert firm.provides_educational_seminars_or_workshops is True
    assert firm.provides_other_advisory_services is False
    assert firm.succession_indicator is True
    assert firm.succession_date == datetime(2026, 4, 22)


def test_item_5g_and_succession_nulls_remain_unavailable():
    firm = normalize_one(
        make_source_row(
            **{
                "5G(1)": "",
                "5G(2)": None,
                "5G(3)": "N",
                "4A": "N",
                "4B": "not-a-date",
            }
        )
    )

    assert firm.provides_financial_planning is None
    assert firm.advises_individuals_or_small_businesses is None
    assert firm.advises_investment_companies is False
    assert firm.succession_indicator is False
    assert firm.succession_date is None
