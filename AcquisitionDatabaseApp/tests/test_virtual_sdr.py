from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.virtual_sdr import (
    SdrBrief,
    build_virtual_sdr_graph,
    configure_langsmith_privacy,
    identify_conflicts,
    identify_gaps,
    sanitized_trace_metadata,
    validate_brief_sources,
    R2ArtifactStore,
)


def context(*, accepted=True, conflicting=False):
    observations = []
    if accepted:
        observations.append({
            "canonical_field": "founder_name",
            "proposed_value": "Jane Doe",
            "source_id": "source-1",
            "evidence_excerpt": "Jane Doe founded the firm.",
        })
    return {
        "firm_id": "123",
        "dataset_version": "ia-test",
        "firm": {"name": "Example Advisers"},
        "facts": {"total_aum": 40_000_000, "employee_count": 3},
        "scores": {"acquisition_score": 91.0, "priority_category": "PRIORITY_A"},
        "accepted_observations": observations,
        "open_observations": [{"review_status": "CONFLICTING", "canonical_field": "founder_name"}] if conflicting else [],
        "official_principals": [],
        "verified_contacts": [],
    }


def brief(source="source-1"):
    return SdrBrief.model_validate({
        "executive_summary": {"text": "Example is a focused advisory firm.", "source_ids": [source]},
        "acquisition_fit_thesis": {"text": "The firm fits SCM's preferred profile.", "source_ids": [source]},
        "decision_makers": [{"name": "Jane Doe", "role": "Founder", "rationale": "Named founder", "source_ids": [source]}],
        "talking_points": [{"text": "Discuss continuity planning.", "source_ids": [source]}],
        "research_gaps": ["No verified email."],
        "email_subject": "A discreet conversation",
        "email_body": "Jane, I would welcome a confidential introductory conversation.",
        "call_opener": "I am calling to introduce SCM and learn about your long-term plans.",
        "discovery_questions": ["What are your goals?", "How is the team structured?", "What matters in a partner?"],
        "likely_objections": [{"objection": "Not considering a transaction", "response": "A relationship can begin without a transaction timetable."}],
        "confidence": "MEDIUM",
        "source_ids": [source],
    })


class FakeRepository:
    def __init__(self, source_context=None):
        self.context = source_context or context()
        self.statuses = []
        self.artifacts = []
        self.finalized = []

    def load_context(self, _firm_id, _dataset_version):
        return self.context

    def set_run_status(self, run_id, status, error_message=None):
        self.statuses.append((run_id, status, error_message))

    def save_artifact(self, run_id, generated, quality, version):
        artifact_id = f"artifact-{version}"
        self.artifacts.append((run_id, generated, quality, version, artifact_id))
        self.set_run_status(run_id, "AWAITING_APPROVAL")
        return {"artifact_id": artifact_id}

    def finalize(self, run_id, artifact_id, decision):
        self.finalized.append((run_id, artifact_id, decision))
        self.set_run_status(run_id, decision)


class FakeGenerator:
    provider = "fake"
    model_name = "fake-model"

    def __init__(self, generated=None, error=None):
        self.generated = generated or brief()
        self.error = error
        self.revisions = []

    def generate(self, _context, _gaps):
        if self.error:
            raise self.error
        return self.generated

    def revise(self, current, notes):
        self.revisions.append(notes)
        updated = current.model_copy(deep=True)
        updated.email_subject = "Revised subject"
        return updated


def initial_state():
    return {"run_id": "run-1", "firm_id": "123", "dataset_version": "ia-test", "input_hash": "hash"}


def test_successful_graph_pauses_for_review_and_resumes_approved():
    repository = FakeRepository()
    graph = build_virtual_sdr_graph(repository, FakeGenerator(), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread-1"}}
    result = graph.invoke(initial_state(), config=config)
    assert result["status"] == "AWAITING_APPROVAL"
    assert result["__interrupt__"]
    assert repository.artifacts[0][3] == 1
    resumed = graph.invoke(Command(resume={"decision": "APPROVED"}), config=config)
    assert resumed["status"] == "APPROVED"
    assert repository.finalized == [("run-1", "artifact-1", "APPROVED")]


def test_revision_creates_new_artifact_and_pauses_again():
    repository = FakeRepository()
    generator = FakeGenerator()
    graph = build_virtual_sdr_graph(repository, generator, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread-revision"}}
    graph.invoke(initial_state(), config=config)
    revised = graph.invoke(Command(resume={"decision": "REVISION_REQUESTED", "notes": "Shorten the subject"}), config=config)
    assert revised["status"] == "AWAITING_APPROVAL"
    assert revised["artifact_version"] == 2
    assert generator.revisions == ["Shorten the subject"]
    assert len(repository.artifacts) == 2


def test_missing_external_evidence_returns_research_required_without_model_call():
    repository = FakeRepository(context(accepted=False))
    generator = FakeGenerator(error=AssertionError("model must not run"))
    result = build_virtual_sdr_graph(repository, generator).invoke(initial_state())
    assert result["status"] == "RESEARCH_REQUIRED"
    assert repository.artifacts == []


def test_conflicting_identity_returns_needs_review():
    repository = FakeRepository(context(conflicting=True))
    result = build_virtual_sdr_graph(repository, FakeGenerator(error=AssertionError("model must not run"))).invoke(initial_state())
    assert result["status"] == "NEEDS_REVIEW"
    assert repository.artifacts == []


def test_unsupported_citation_fails_quality_gate():
    repository = FakeRepository()
    result = build_virtual_sdr_graph(repository, FakeGenerator(brief("invented-source"))).invoke(initial_state())
    assert result["status"] == "FAILED"
    assert repository.artifacts == []


def test_provider_failure_is_preserved_for_retry():
    repository = FakeRepository()
    result = build_virtual_sdr_graph(repository, FakeGenerator(error=TimeoutError("provider timeout"))).invoke(initial_state())
    assert result["status"] == "FAILED"
    assert "provider timeout" in result["error_message"]
    assert repository.statuses[-1][1] == "FAILED"


def test_trace_metadata_contains_counts_but_no_evidence_or_contacts():
    state = {**initial_state(), "context": context()}
    metadata = sanitized_trace_metadata(state)
    assert metadata["accepted_fact_count"] == 1
    serialized = str(metadata)
    assert "Jane Doe" not in serialized
    assert "evidence_excerpt" not in serialized


def test_langsmith_privacy_defaults_hide_inputs_and_outputs(monkeypatch):
    monkeypatch.delenv("LANGSMITH_HIDE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_OUTPUTS", raising=False)
    configure_langsmith_privacy()
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true"
    assert os.environ["LANGSMITH_HIDE_OUTPUTS"] == "true"


def test_quality_validation_preserves_null_and_zero_and_rejects_unknown_sources():
    generated = brief()
    generated.research_gaps = ["Employee count may be 0; unavailable values remain null."]
    passed = validate_brief_sources(generated, ["source-1"])
    failed = validate_brief_sources(brief("unknown"), ["source-1"])
    assert passed.status == "PASSED"
    assert failed.status == "FAILED"
    assert failed.unsupported_source_ids == ["unknown"]


def test_gap_and_conflict_detection_are_deterministic():
    gaps = identify_gaps(context())
    assert "No verified outreach contact is available." in gaps
    assert identify_conflicts(context()) == []
    assert identify_conflicts(context(conflicting=True))


def test_non_identity_conflict_is_disclosed_as_gap_without_blocking():
    source_context = context()
    source_context["open_observations"] = [{
        "review_status": "CONFLICTING", "canonical_field": "primary_custodian"
    }]
    assert identify_conflicts(source_context) == []
    assert "1 non-identity research conflict(s) remain unresolved." in identify_gaps(source_context)


def test_r2_artifact_upload_is_private_bounded_json_with_hash(monkeypatch):
    calls = []

    class FakeClient:
        def put_object(self, **kwargs):
            calls.append(kwargs)
            return {"ETag": '"etag-1"'}

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda *args, **kwargs: FakeClient()))
    store = R2ArtifactStore("account", "access", "secret", "bucket")
    result = store.put("virtual-sdr/run/brief.json", b'{"safe":true}')
    assert result == {"key": "virtual-sdr/run/brief.json", "etag": "etag-1"}
    assert calls[0]["Bucket"] == "bucket"
    assert calls[0]["ContentType"] == "application/json"
    assert len(calls[0]["Metadata"]["sha256"]) == 64
    assert "ACL" not in calls[0]
