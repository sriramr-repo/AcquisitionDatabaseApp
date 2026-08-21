from __future__ import annotations

import sys

import pytest

from src import iapd_live
from src.iapd_live import IAPDLiveUnavailable, build_iapd_individual_url, capture_iapd_live_page, normalize_iapd_live_markdown


LIVE_MARKDOWN = """# Jane Advisor
Individual CRD: 12345
Current Employer: Example Advisory LLC
Current Employer CRD: 98765
Business Address: 1 Main St, Boston, MA 02110
Phone: (617) 555-0100
Website: https://example.com
Registration Status: Approved
Registration Date: 2026-08-04
Branch: Boston office
Disclosure Summary: No disclosures reported
"""


def test_live_markdown_normalization_preserves_labelled_fields():
    result = normalize_iapd_live_markdown(LIVE_MARKDOWN, expected_crd="12345")
    fields = result["fields"]
    assert fields["individual_crd"] == "12345"
    assert fields["current_employer_crd"] == "98765"
    assert fields["phone"] == "(617) 555-0100"
    assert fields["branch_locations"] == ["Boston office"]
    assert result["confidence"] == "HIGH"


def test_live_normalization_flags_mismatched_crd_instead_of_guessing():
    with pytest.raises(IAPDLiveUnavailable):
        normalize_iapd_live_markdown(LIVE_MARKDOWN, expected_crd="99999")


def test_live_capture_requires_configured_firecrawl_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.setattr(iapd_live, "PROJECT_ROOT", __import__("pathlib").Path("/missing"))
    with pytest.raises(IAPDLiveUnavailable, match="FIRECRAWL_API_KEY"):
        capture_iapd_live_page(individual_crd="12345", database_url="postgresql://unused")


def test_live_capture_can_use_existing_local_dashboard_environment(tmp_path, monkeypatch):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / ".env.local").write_text('FIRECRAWL_API_KEY="stored-key"\n')
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.setattr(iapd_live, "PROJECT_ROOT", tmp_path)
    assert iapd_live._firecrawl_api_key() == "stored-key"


def test_live_iapd_url_is_stable_and_crd_specific():
    assert build_iapd_individual_url("12345").endswith("/individual/summary/12345")


def test_live_capture_uses_firecrawl_and_records_provenance(monkeypatch):
    statements = []
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"data": {"markdown": LIVE_MARKDOWN, "metadata": {"title": "IAPD Jane"}}}
    class Session:
        def post(self, url, headers, json, timeout):
            assert "Bearer test-key" == headers["Authorization"]
            assert json["onlyMainContent"] is True
            return Response()
    class Transaction:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def transaction(self): return Transaction()
        def execute(self, statement, params): statements.append((statement, params))
    class Psycopg:
        @staticmethod
        def connect(*args, **kwargs): return Connection()
    monkeypatch.setitem(sys.modules, "psycopg", Psycopg)
    monkeypatch.setattr(iapd_live, "reconcile_iapd_individual", lambda **_: {"freshness": "live_confirmed"})
    result = capture_iapd_live_page(individual_crd="12345", database_url="postgresql://unused", api_key="test-key", session=Session())
    assert result["status"] == "success"
    assert result["reconciliation"]["freshness"] == "live_confirmed"
    assert len(statements) == 2
    assert "iapd_live_captures" in statements[0][0]
    assert "iapd_individual_live_enrichments" in statements[1][0]
