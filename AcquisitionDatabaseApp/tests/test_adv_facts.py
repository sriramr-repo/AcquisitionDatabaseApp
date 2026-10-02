from pathlib import Path
import csv
import io
import zipfile

import pytest

from src.adv_facts import extract_record, iter_bulk_records, parse_bool, parse_number, validate_pdf
from src.adv_ocr import _auto_accept, _grounded, parse_custodians, parse_custodians_with_langchain, CustodianCandidate
from src.fact_catalog import records


def sample_row() -> dict[str, str]:
    return {
        "Organization CRD#": "319716", "SEC#": "801-12345", "Legal Name": "EXAMPLE ADVISER LLC", "Date Submitted": "08/01/2026",
        "1O": "N", "1O - If yes, approx. amount of assets": "", "2A(2)": "Y", "4A": "N", "4B": "",
        "5A": " 1 ", "5B(1)": "1", "5B(2)": "0", "5B(3)": "1", "5B(4)": "", "5B(5)": "0", "5B(6)": "",
        "5D(a)(1)": "9", "5D(a)(2)": "N", "5D(a)(3)": "$581,619", "5D(b)(1)": "5", "5D(b)(2)": "", "5D(b)(3)": "25,970,196",
        "5E(1)": "Y", "5E(4)": "Y", "5E(7)": "Y", "5E(7)-Other": "Project fees", "5F(1)": "Y", "5F(2)(a)": "$26,551,815", "5F(2)(b)": "0", "5F(2)(c)": "26,551,815",
        "5F(2)(d)": "24", "5F(2)(e)": "0", "5F(2)(f)": "24", "5F(3)": "0", "5G(1)": "Y", "5G(2)": "Y", "5K(4)": "Y",
    }


def test_structured_adv_extraction_preserves_null_and_zero():
    record = extract_record(sample_row(), "ia08032026")
    assert record.filing["firm_id"] == "319716"
    assert record.filing["pdf_url"].endswith("/319716.pdf")
    assert record.facts["item_1o_over_1b"] is False
    assert record.facts["other_adviser_iar_count"] is None
    assert record.facts["insurance_agent_count"] == 0
    assert record.facts["total_aum"] == 26_551_815
    assert record.facts["sec_registration_basis"] == [{"code": "2", "label": "Mid-sized advisory firm", "source_field": "2A(2)"}]
    assert record.facts["compensation_arrangements"][-1]["other_text"] == "Project fees"
    assert record.facts["client_categories"][0]["aum"] == 581_619
    assert record.facts["client_categories"][2]["client_count"] is None


def test_parsers_handle_commas_whitespace_and_unknowns():
    assert parse_number(" 1,234 ", integer=True) == 1234
    assert parse_number("") is None
    assert parse_bool("Y") is True
    assert parse_bool("Fewer than 5 clients") is True
    assert parse_bool("0") is False
    assert parse_bool("unknown") is None


def test_bulk_zip_iteration(tmp_path: Path):
    path = tmp_path / "ia.zip"
    headers = list(sample_row())
    content = io.StringIO()
    writer = csv.DictWriter(content, fieldnames=headers)
    writer.writeheader(); writer.writerow(sample_row())
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("firms.csv", content.getvalue())
    records_found = list(iter_bulk_records(path, "ia08032026", {"319716"}))
    assert len(records_found) == 1
    assert records_found[0].facts["employee_count"] == 1


def test_pdf_validation_rejects_placeholder():
    with pytest.raises(ValueError, match="not a PDF"):
        validate_pdf(b"dummy.csv", "319716")


def test_schedule_5k_custodian_parser():
    text = """SECTION 5.K.(3) Custodians for Separately Managed Accounts
    (a) Legal name of custodian: INTERACTIVE BROKERS LLC
    (b) Primary business name of custodian: INTERACTIVE BROKERS LLC
    (c) City: GREENWICH State: Connecticut Country: United States
    (d) Is the custodian a related person of your firm? No
    (e) SEC registration number 8 - 47257
    (g) What amount of your regulatory assets under management attributable to separately managed accounts is held at the custodian? $ 26,551,815
    Item 6 Other Business Activities"""
    candidates = parse_custodians(text)
    assert len(candidates) == 1
    assert candidates[0].legal_name == "INTERACTIVE BROKERS LLC"
    assert candidates[0].broker_dealer_sec_number == "8-47257"
    assert candidates[0].sma_aum == 26_551_815
    assert (candidates[0].city, candidates[0].state, candidates[0].country) == ("GREENWICH", "Connecticut", "United States")


def test_schedule_5k_parser_handles_stacked_location_labels():
    text = """SECTION 5.K.(3)
    (a) Legal name of custodian: CHARLES SCHWAB
    (b) Primary business name of custodian: CHARLES SCHWAB
    (c) City: State: Country: WESTLAKE Texas United States Yes No
    (d) Is the custodian a related person of your firm?
    (g) amount held at the custodian? $ 1,402,005
    Item 6"""
    candidate = parse_custodians(text)[0]
    assert (candidate.city, candidate.state, candidate.country) == ("WESTLAKE", "Texas", "United States")


def test_schedule_5k_parser_handles_official_multiline_pdf_layout():
    text = """--- PAGE 31 ---
    SECTION 5.K.(3) Custodians for Separately Managed Accounts
    (a)          Legal name of custodian:
                 CHARLES SCHWAB & CO., INC.
    (b)          Primary business name of custodian:
                 CHARLES SCHWAB & CO., INC.
    (c)          The location of the custodian
                 City:                         State:                    Country:
                 WESTLAKE                      Texas                     United States
    (d)          Is the custodian a related person of your firm?
    (e)          SEC registration number 8 - 16514
    (g)          amount held at the custodian?
                 $ 304,029,000
    Item 6"""
    candidate = parse_custodians(text)[0]
    assert candidate.legal_name == "CHARLES SCHWAB & CO., INC."
    assert candidate.primary_business_name == "CHARLES SCHWAB & CO., INC."
    assert (candidate.city, candidate.state, candidate.country) == ("WESTLAKE", "Texas", "United States")
    assert candidate.sma_aum == 304_029_000
    assert candidate.source_page == 31


def test_schedule_5k_parser_retains_source_page_and_deduplicates():
    block = """(a) Legal name of custodian: TEST CUSTODIAN LLC
    (b) Primary business name of custodian: TEST CUSTODIAN
    (c) City: BOSTON State: Massachusetts Country: United States
    (g) amount held at the custodian? $ 5,000"""
    candidates = parse_custodians(f"--- PAGE 12 ---\nSECTION 5.K.(3)\n{block}\n{block}\nItem 6")
    assert len(candidates) == 1
    assert candidates[0].source_page == 12


def test_langchain_fallback_is_disabled_by_default_and_requires_grounding(monkeypatch):
    monkeypatch.delenv("ADV_CUSTODIAN_LANGCHAIN_ENABLED", raising=False)
    assert parse_custodians_with_langchain("SECTION 5.K.(3)") == []
    assert _grounded(CustodianCandidate("REAL CUSTODIAN", sma_aum=1000), "REAL CUSTODIAN $1,000") is True
    assert _grounded(CustodianCandidate("INVENTED CUSTODIAN"), "REAL CUSTODIAN") is False


def test_custodian_auto_acceptance_requires_grounded_name_amount_and_page():
    source = "--- PAGE 12 --- TEST CUSTODIAN LLC amount held at the custodian $ 5,000"
    complete = CustodianCandidate("TEST CUSTODIAN LLC", sma_aum=5_000, source_page=12)
    assert _auto_accept(complete, source, "DETERMINISTIC_OCR")[0] is True
    assert _auto_accept(CustodianCandidate("TEST CUSTODIAN LLC", source_page=12), source, "DETERMINISTIC_OCR")[0] is False
    assert _auto_accept(CustodianCandidate("TEST CUSTODIAN LLC", sma_aum=5_000), source, "DETERMINISTIC_OCR")[0] is False
    assert _auto_accept(CustodianCandidate("INVENTED", sma_aum=5_000, source_page=12), source, "LANGCHAIN_GROUNDED_FALLBACK")[0] is False


def test_custodian_auto_acceptance_preserves_zero_aum():
    candidate = CustodianCandidate("ZERO CUSTODIAN", sma_aum=0, source_page=4)
    assert _auto_accept(candidate, "ZERO CUSTODIAN $ 0", "DETERMINISTIC_OCR")[0] is True


def test_custodian_auto_acceptance_allows_grounded_langchain_fallback():
    candidate = CustodianCandidate("VERIFIED BANK LLC", sma_aum=1_250_000, source_page=44)
    source = "--- PAGE 44 --- VERIFIED BANK LLC amount held at the custodian $ 1,250,000"
    accepted, reason = _auto_accept(candidate, source, "LANGCHAIN_GROUNDED_FALLBACK")
    assert accepted is True
    assert "grounded" in reason


def test_fact_catalog_has_unique_source_backed_keys():
    catalog = records()
    assert len({item["field_key"] for item in catalog}) == len(catalog)
    assert all(item["primary_source_type"] and item["null_meaning"] for item in catalog)
    seller = next(item for item in catalog if item["field_key"] == "seller_intent.status")
    assert seller["requires_evidence"] is True
    assert seller["used_in_scoring"] is False
