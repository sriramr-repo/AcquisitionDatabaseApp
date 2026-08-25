from __future__ import annotations

import csv
import io
import zipfile

from src.adv_principals import (
    COVERAGE_STATUSES,
    classify_coverage,
    iter_adv_principals,
    parse_adv_principal_csv,
)


SCHEDULE_A = """Organization CRD#,Filing Date,Full Legal Name,DE/FE/I,Title or Status,Ownership Code,Control Person,CRD No.
167463,2026-01-03,"GLASSMAN, JAY, TOBY",I,PRESIDENT AND CHIEF COMPLIANCE OFFICER,D,Y,2491695
167463,2026-01-03,GLASSMAN HOLDINGS LLC,DE,MEMBER,E,Y,
"""


SCHEDULE_B = """Firm CRD,Schedule Type,Owner Name,Entity Type,Title/Status,Ownership,Control,Related CRD
330914,B,"OWNER, SAMPLE",I,MEMBER,E,Yes,7654321
"""


SEC_PREFIXED_SCHEDULE_A = """OrgCRD,FilingDt,DV_FullLegalName,DV_DE_F,DV_Title,DV_OwnershipCode,DV_ControlPerson,DV_CRDNum
167463,01/03/2026,"GLASSMAN, JAY, TOBY",I,PRESIDENT,D,Y,2491695
"""


def test_schedule_a_parser_preserves_people_entities_and_provenance():
    rows = list(parse_adv_principal_csv(
        io.StringIO(SCHEDULE_A), source_name="Schedule_A.csv", content_hash="abc"
    ))
    assert len(rows) == 2
    assert rows[0]["firm_id"] == "167463"
    assert rows[0]["schedule_type"] == "A"
    assert rows[0]["principal_type"] == "INDIVIDUAL"
    assert rows[0]["related_crd"] == "2491695"
    assert rows[0]["control_person"] is True
    assert rows[1]["principal_type"] == "DOMESTIC_ENTITY"
    assert rows[0]["principal_id"] != rows[1]["principal_id"]


def test_schedule_b_parser_uses_explicit_schedule_column():
    row = list(parse_adv_principal_csv(
        io.StringIO(SCHEDULE_B), source_name="owners.csv", content_hash="def"
    ))[0]
    assert row["schedule_type"] == "B"
    assert row["full_legal_name"] == "OWNER, SAMPLE"
    assert row["related_crd"] == "7654321"


def test_official_prefixed_columns_and_dates_are_normalized():
    row = list(parse_adv_principal_csv(
        io.StringIO(SEC_PREFIXED_SCHEDULE_A),
        source_name="Schedule_A_Direct_Owners.csv",
        content_hash="ghi",
    ))[0]
    assert row["firm_id"] == "167463"
    assert row["filing_date"] == "2026-01-03"
    assert row["principal_type"] == "INDIVIDUAL"
    assert row["related_crd"] == "2491695"


def test_zip_parser_skips_unrelated_tables(tmp_path):
    path = tmp_path / "adv.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Schedule_A.csv", SCHEDULE_A)
        archive.writestr("Firm_Roster.csv", "Organization CRD#,Legal Name\n1,Firm\n")
    rows = list(iter_adv_principals(path))
    assert len(rows) == 2
    assert {row["schedule_type"] for row in rows} == {"A"}


def test_coverage_classification_has_explicit_precedence():
    assert classify_coverage(
        summary_present=False, representative_count=None, reported_state_iar_count=None
    ) == "SOURCE_NOT_PROCESSED"
    assert classify_coverage(
        summary_present=True, representative_count=1, reported_state_iar_count=0,
        schedule_a_individuals=1,
    ) == "CURRENT_IAPD_REPRESENTATIVE"
    assert classify_coverage(
        summary_present=True, representative_count=0, reported_state_iar_count=2,
        schedule_a_individuals=1,
    ) == "RECONCILIATION_REQUIRED"
    assert classify_coverage(
        summary_present=True, representative_count=0, reported_state_iar_count=0,
        schedule_a_individuals=1,
    ) == "SCHEDULE_A_PRINCIPAL"
    assert classify_coverage(
        summary_present=True, representative_count=0, reported_state_iar_count=0,
        schedule_b_individuals=1,
    ) == "SCHEDULE_B_OWNER"
    assert classify_coverage(
        summary_present=True, representative_count=0, reported_state_iar_count=0,
        entity_principals=1,
    ) == "ENTITY_OWNER_ONLY"
    assert classify_coverage(
        summary_present=True, representative_count=0, reported_state_iar_count=0,
        cco_or_signatory_count=1,
    ) == "CCO_OR_SIGNATORY_ONLY"
    assert classify_coverage(
        summary_present=True, representative_count=0, reported_state_iar_count=0,
    ) == "NO_PUBLIC_INDIVIDUAL_PROFILE"
    assert classify_coverage(
        summary_present=False, representative_count=None, reported_state_iar_count=None,
        source_retrieval_failed=True,
    ) == "SOURCE_RETRIEVAL_FAILED"


def test_every_classified_value_is_in_the_dashboard_contract():
    expected = {
        "CURRENT_IAPD_REPRESENTATIVE", "SCHEDULE_A_PRINCIPAL", "SCHEDULE_B_OWNER",
        "ENTITY_OWNER_ONLY", "NO_PUBLIC_INDIVIDUAL_PROFILE",
        "RECONCILIATION_REQUIRED", "SOURCE_NOT_PROCESSED",
    }
    assert expected <= COVERAGE_STATUSES
