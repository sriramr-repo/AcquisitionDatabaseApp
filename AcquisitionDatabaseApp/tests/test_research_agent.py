from __future__ import annotations

import os
import time

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from src.cli import app

from src.research_agent import (
    BatchResearchExtraction,
    EvidenceCapture,
    EvidenceChunk,
    InvalidExtraction,
    PROMPT_VERSION,
    EXTRACTION_VERSION,
    ProposedObservation,
    ResearchAgentConfig,
    ResearchAgentService,
    ResearchAgentUnavailable,
    TransientResearchAgentError,
    ResearchExtraction,
    LangChainOllamaExtractor,
    LangChainOpenAIExtractor,
    LangChainFreeTokenExtractor,
    PostgresResearchAgentRepository,
    build_service,
    batch_chunks,
    batch_seed,
    bound_captures,
    chunk_capture,
    chunk_payload,
    classify_provider_error,
    invoke_with_deadline,
    extract_chunk_batches,
    filter_valid_observations,
    freetoken_health_url,
    merge_extractions,
    select_relevant_chunks,
    source_set_digest,
    provider_unavailable_message,
    sanitize_extraction,
    normalize_single_capture_references,
    normalize_exact_evidence_references,
    normalize_openai_base_url,
    validate_extraction,
    configure_langsmith_privacy,
)


def capture(capture_id="capture-1", content="Founder Jane Doe leads the firm."):
    return EvidenceCapture(
        capture_id=capture_id,
        source_id=f"source-{capture_id}",
        source_type="official_website",
        source_url="https://example.com/about",
        source_title="About",
        content_hash=f"hash-{capture_id}",
        content=content,
    )


def observation(**overrides):
    default_chunk = chunk_capture(capture(), 6000)[0]
    values = {
        "canonical_field": "founder_name",
        "proposed_value": "Jane Doe",
        "value_type": "FACT",
        "confidence": "HIGH",
        "source_capture_id": "capture-1",
        "source_chunk_id": default_chunk.chunk_id,
        "evidence_excerpt": "Founder Jane Doe leads the firm.",
    }
    values.update(overrides)
    return ProposedObservation(**values)


class FakeExtractor:
    provider = "fake"
    model_name = "fake-model"

    def __init__(self, result=None, error=None):
        self.result = result or ResearchExtraction()
        self.error = error

    def extract(self, **_):
        if self.error:
            raise self.error
        return self.result


class FakeRepository:
    def __init__(self, captures=None, jobs=None, batch_candidates=None):
        self.captures = captures or [capture()]
        self.jobs = jobs or []
        self.statuses = []
        self.saved = []
        self.claim_args = None
        self.batch_candidates = batch_candidates or []

    def load_captures(self, _firm_id, _dataset_version, capture_ids=None):
        allowed = set(capture_ids or ())
        return [item for item in self.captures if not allowed or item.capture_id in allowed]

    def queue_job(self, **kwargs):
        return {"job_id": "job-1", "status": "QUEUED", **kwargs}

    def priority_a_batch_candidates(self, _dataset_version, limit):
        return self.batch_candidates[:limit]

    def next_jobs(self, limit, *, worker_id, lease_seconds):
        self.claim_args = (limit, worker_id, lease_seconds)
        return self.jobs[:limit]

    def set_job_status(self, job_id, status, error_message=None, **details):
        self.statuses.append((job_id, status, error_message, details))

    def save_observations(self, **kwargs):
        self.saved.extend(kwargs["extraction"].observations)
        return len(kwargs["extraction"].observations)


def job(capture_ids=None):
    return {
        "job_id": "job-1",
        "firm_id": "firm-1",
        "dataset_version": "ia-test",
        "source_capture_ids": capture_ids or ["capture-1"],
        "prompt_version": PROMPT_VERSION,
        "extraction_version": EXTRACTION_VERSION,
        "model_provider": "fake",
        "model_name": "fake-model",
        "attempt_count": 1,
        "max_attempts": 3,
        "max_pages": 6,
        "max_tokens": 4000,
        "timeout_seconds": 60,
        "max_content_chars": 120000,
        "max_chunk_chars": 6000,
        "max_chunks": 18,
        "max_chunks_per_request": 2,
    }


def test_valid_structured_extraction_is_saved_as_proposed():
    repository = FakeRepository()
    extractor = FakeExtractor(ResearchExtraction(observations=[observation()]))
    result = ResearchAgentService(repository, extractor, ResearchAgentConfig()).process_job(job())
    assert result == {"job_id": "job-1", "status": "REVIEW_REQUIRED", "observations": 1}
    assert repository.saved[0].proposed_value == "Jane Doe"
    assert repository.statuses[-1][1] == "REVIEW_REQUIRED"


def test_research_agent_langsmith_traces_hide_evidence_by_default(monkeypatch):
    monkeypatch.delenv("LANGSMITH_HIDE_INPUTS", raising=False)
    monkeypatch.delenv("LANGSMITH_HIDE_OUTPUTS", raising=False)
    configure_langsmith_privacy()
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true"
    assert os.environ["LANGSMITH_HIDE_OUTPUTS"] == "true"


def test_priority_a_batch_queue_is_bounded_and_uses_normal_queue_flow():
    repository = FakeRepository(batch_candidates=[f"firm-{index}" for index in range(30)])
    service = ResearchAgentService(repository, FakeExtractor(), ResearchAgentConfig())
    result = service.queue_priority_a_batch(
        dataset_version="ia-test", limit=5, requested_by="analyst@example.com"
    )
    assert result["priority"] == "PRIORITY_A"
    assert result["selected"] == 5
    assert result["queued"] == 5
    assert result["failed"] == 0
    assert len(result["job_ids"]) == 5


@pytest.mark.parametrize("limit", [0, 26])
def test_priority_a_batch_queue_rejects_unsafe_limits(limit):
    service = ResearchAgentService(FakeRepository(), FakeExtractor(), ResearchAgentConfig())
    with pytest.raises(ValueError, match="between 1 and 25"):
        service.queue_priority_a_batch(dataset_version="ia-test", limit=limit)


def test_priority_a_batch_queue_reports_per_firm_failure_without_stopping_batch():
    class PartiallyFailingRepository(FakeRepository):
        def load_captures(self, firm_id, dataset_version, capture_ids=None):
            if firm_id == "firm-bad":
                return []
            return super().load_captures(firm_id, dataset_version, capture_ids)

    repository = PartiallyFailingRepository(
        batch_candidates=["firm-good", "firm-bad", "firm-after"]
    )
    result = ResearchAgentService(
        repository, FakeExtractor(), ResearchAgentConfig()
    ).queue_priority_a_batch(dataset_version="ia-test", limit=3)
    assert result["queued"] == 2
    assert result["failed"] == 1
    assert result["failures"][0]["firm_id"] == "firm-bad"


def test_empty_priority_a_batch_is_a_successful_no_op():
    result = ResearchAgentService(
        FakeRepository(batch_candidates=[]), FakeExtractor(), ResearchAgentConfig()
    ).queue_priority_a_batch(dataset_version="ia-test", limit=10)
    assert result["selected"] == result["queued"] == result["failed"] == 0


def test_stale_job_contract_is_rejected_before_model_or_persistence():
    class NeverCalledExtractor(FakeExtractor):
        def extract(self, **_):
            raise AssertionError("stale job reached extractor")

    repository = FakeRepository()
    stale = job()
    stale["extraction_version"] = "stale-version"
    result = ResearchAgentService(
        repository, NeverCalledExtractor(), ResearchAgentConfig()
    ).process_job(stale)
    assert result["status"] == "FAILED"
    assert "contract version is stale" in result["error"]
    assert repository.saved == []


def test_stale_job_provider_is_rejected_before_model_or_persistence():
    repository = FakeRepository()
    stale = job()
    stale["model_provider"] = "ollama"
    result = ResearchAgentService(
        repository, FakeExtractor(), ResearchAgentConfig()
    ).process_job(stale)
    assert result["status"] == "FAILED"
    assert "provider configuration is stale" in result["error"]
    assert repository.saved == []


def test_unknown_provenance_rejects_entire_extraction():
    extraction = ResearchExtraction(
        observations=[observation(source_capture_id="missing-capture")]
    )
    with pytest.raises(InvalidExtraction, match="unknown capture"):
        validate_extraction(extraction, [capture()])


def test_malformed_structured_output_is_rejected():
    with pytest.raises(ValidationError):
        ResearchExtraction.model_validate(
            {"observations": [{"canonical_field": "sale_intent", "confidence": "CERTAIN"}]}
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"proposed_value": "x" * 401},
        {"evidence_excerpt": "x" * 301},
    ],
)
def test_verbose_observation_fields_are_rejected_by_the_schema(overrides):
    with pytest.raises(ValidationError):
        observation(**overrides)


def test_each_model_batch_is_limited_to_three_observations():
    with pytest.raises(ValidationError):
        BatchResearchExtraction(observations=[observation() for _ in range(4)])


def test_provider_unavailability_marks_job_unavailable():
    repository = FakeRepository()
    extractor = FakeExtractor(error=ResearchAgentUnavailable("provider unavailable"))
    result = ResearchAgentService(repository, extractor, ResearchAgentConfig()).process_job(job())
    assert result["status"] == "UNAVAILABLE"
    assert repository.statuses[-1][1] == "UNAVAILABLE"


def test_insufficient_quota_is_classified_as_provider_unavailable():
    error = RuntimeError("429: insufficient_quota - exceeded your current quota")
    assert provider_unavailable_message(error) == "OpenAI API quota or billing is unavailable"


def test_transient_rate_limit_is_not_misclassified_as_quota_exhaustion():
    error = RuntimeError("429: rate_limit_exceeded; retry after 1 second")
    assert provider_unavailable_message(error) is None


def test_timeout_or_firecrawl_capture_failure_marks_job_failed():
    repository = FakeRepository()
    extractor = FakeExtractor(error=TimeoutError("captured source processing timed out"))
    result = ResearchAgentService(repository, extractor, ResearchAgentConfig()).process_job(job())
    assert result["status"] == "FAILED"
    assert repository.statuses[-1][1] == "FAILED"


def test_iapd_source_mismatch_is_rejected_by_provenance_check():
    extraction = ResearchExtraction(
        observations=[observation(source_capture_id="iapd-capture-for-another-firm")]
    )
    with pytest.raises(InvalidExtraction, match="unknown capture"):
        validate_extraction(extraction, [capture("iapd-capture-for-this-firm")])


def test_page_limit_does_not_allow_first_source_to_consume_other_sources():
    captures = [capture(f"capture-{index}", "x" * 10) for index in range(4)]
    bounded = bound_captures(
        captures,
        ResearchAgentConfig(max_pages=2, max_content_chars=15),
    )
    assert len(bounded) == 2
    assert [len(item.content) for item in bounded] == [10, 10]


def test_selected_chunk_content_respects_total_budget():
    captures = [
        capture("capture-1", "# About\n" + "Founder and services. " * 20),
        capture("capture-2", "# Contact\n" + "Contact and client details. " * 20),
    ]
    config = ResearchAgentConfig(
        max_pages=2, max_content_chars=600, max_chunk_chars=300, max_chunks=10
    )
    selected = select_relevant_chunks(bound_captures(captures, config), config)
    assert sum(len(item.content) for item in selected) <= 600


def test_source_set_digest_is_order_independent_for_idempotency():
    one, two = capture("one"), capture("two")
    assert source_set_digest([one, two]) == source_set_digest([two, one])


def test_conflicting_values_remain_separate_proposals():
    source_capture = capture(
        content="Founder Jane Doe leads the firm. John Doe founded the firm."
    )
    source_chunk = chunk_capture(source_capture, 6000)[0]
    extraction = ResearchExtraction(
        observations=[
            observation(proposed_value="Jane Doe", source_chunk_id=source_chunk.chunk_id),
            observation(
                proposed_value="John Doe",
                evidence_excerpt="John Doe founded the firm.",
                source_chunk_id=source_chunk.chunk_id,
            ),
        ]
    )
    repository = FakeRepository(captures=[source_capture])
    result = ResearchAgentService(
        repository, FakeExtractor(extraction), ResearchAgentConfig()
    ).process_job(job())
    assert result["observations"] == 2
    assert [item.proposed_value for item in repository.saved] == ["Jane Doe", "John Doe"]


def test_null_and_zero_remain_distinct():
    extraction = ResearchExtraction(
        observations=[
            observation(canonical_field="contact_phone", proposed_value=None),
            observation(canonical_field="services_summary", proposed_value="0"),
        ]
    )
    assert extraction.observations[0].proposed_value is None
    assert extraction.observations[1].proposed_value == "0"


def test_unavailable_placeholder_observations_are_dropped():
    extraction = ResearchExtraction(
        observations=[
            observation(proposed_value="Not explicitly stated"),
            observation(canonical_field="contact_email", proposed_value="jane@example.com"),
        ]
    )
    cleaned = sanitize_extraction(extraction)
    assert [item.proposed_value for item in cleaned.observations] == ["jane@example.com"]


def test_duplicate_observations_are_deduplicated():
    item = observation()
    cleaned = sanitize_extraction(ResearchExtraction(observations=[item, item]))
    assert len(cleaned.observations) == 1


def test_chunks_are_split_into_deterministic_bounded_batches():
    chunks = chunk_capture(capture(content="Founder and services. " * 200), 500)[:5]
    batches = batch_chunks(chunks, 2)
    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert [item.chunk_id for batch in batches for item in batch] == [
        item.chunk_id for item in chunks
    ]


def test_invalid_batch_size_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        batch_chunks([], 0)


def test_batch_seed_is_distinct_across_batches_and_retries():
    assert {batch_seed(attempt, batch) for attempt in (1, 2) for batch in range(3)} == {
        0, 1, 2, 1000, 1001, 1002
    }


def test_merged_batches_dedupe_exact_values_preserve_conflicts_and_cap_output():
    source = capture(content="Founder Jane Doe. Founder John Doe. " + "Service fact. " * 10)
    source_chunk = chunk_capture(source, 6000)[0]
    jane = observation(
        proposed_value="Jane Doe",
        evidence_excerpt="Founder Jane Doe.",
        source_chunk_id=source_chunk.chunk_id,
    )
    john = observation(
        proposed_value="John Doe",
        evidence_excerpt="Founder John Doe.",
        source_chunk_id=source_chunk.chunk_id,
    )
    extras = [
        observation(
            canonical_field="services_summary",
            proposed_value=f"Service {index}",
            evidence_excerpt="Service fact.",
            source_chunk_id=source_chunk.chunk_id,
        )
        for index in range(8)
    ]
    merged = merge_extractions(
        [ResearchExtraction(observations=[jane, jane, john]), ResearchExtraction(observations=extras)]
    )
    assert len(merged.observations) == 8
    assert [item.proposed_value for item in merged.observations[:2]] == ["Jane Doe", "John Doe"]


def test_failed_later_batch_returns_no_partial_extraction():
    source = capture(content="Founder Jane Doe. " * 100)
    chunks = chunk_capture(source, 500)[:3]
    calls = []

    def invoke(batch, batch_index):
        calls.append(batch_index)
        if batch_index == 1:
            raise TimeoutError("model timed out")
        item = batch[0]
        return ResearchExtraction(observations=[observation(
            source_chunk_id=item.chunk_id,
            evidence_excerpt="Founder Jane Doe.",
        )])

    with pytest.raises(TransientResearchAgentError):
        extract_chunk_batches(
            chunks=chunks,
            captures=[source],
            batch_size=2,
            invoke_batch=invoke,
        )
    assert calls == [0, 1]


def test_invalid_observation_is_rejected_without_discarding_valid_peer():
    source = capture()
    source_chunk = chunk_capture(source, 6000)[0]
    extraction = ResearchExtraction(observations=[
        observation(source_chunk_id=source_chunk.chunk_id),
        observation(
            canonical_field="contact_profile_url",
            proposed_value="https://example.com",
            source_chunk_id=source_chunk.chunk_id,
            evidence_excerpt="source_url: https://example.com",
        ),
    ])
    valid, rejected = filter_valid_observations(extraction, [source], [source_chunk])
    assert rejected == 1
    assert [item.proposed_value for item in valid.observations] == ["Jane Doe"]


def test_batch_extraction_fails_when_every_observation_lacks_valid_provenance():
    source = capture()
    source_chunk = chunk_capture(source, 6000)[0]

    def invoke(_batch, _batch_index):
        return ResearchExtraction(observations=[observation(
            source_chunk_id=source_chunk.chunk_id,
            evidence_excerpt="source_url: https://example.com",
        )])

    with pytest.raises(InvalidExtraction, match="all model observations"):
        extract_chunk_batches(
            chunks=[source_chunk],
            captures=[source],
            batch_size=1,
            invoke_batch=invoke,
        )


def test_evidence_excerpt_must_exist_in_cited_capture():
    extraction = ResearchExtraction(
        observations=[observation(evidence_excerpt="Text absent from source")]
    )
    with pytest.raises(InvalidExtraction, match="not present"):
        validate_extraction(extraction, [capture()])


def test_single_capture_reference_is_deterministically_rebound():
    extraction = ResearchExtraction(
        observations=[observation(source_capture_id="1")]
    )
    rebound = normalize_single_capture_references(extraction, [capture()])
    assert rebound.observations[0].source_capture_id == "capture-1"


def test_multiple_capture_reference_is_never_guessed():
    extraction = ResearchExtraction(
        observations=[observation(source_capture_id="1")]
    )
    captures = [capture("capture-1"), capture("capture-2")]
    unchanged = normalize_single_capture_references(extraction, captures)
    assert unchanged.observations[0].source_capture_id == "1"


def test_agent_has_no_research_or_outreach_mutation_path():
    repository = FakeRepository()
    service = ResearchAgentService(
        repository,
        FakeExtractor(ResearchExtraction(observations=[observation()])),
        ResearchAgentConfig(),
    )
    service.process_job(job())
    assert not hasattr(repository, "update_firm_research")
    assert not hasattr(repository, "update_outreach")


def test_ollama_is_the_default_local_provider():
    config = ResearchAgentConfig()
    assert config.provider == "ollama"
    assert config.model == "qwen3:8b"


def test_provider_selection_remains_configurable(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "ollama")
    monkeypatch.setenv("RESEARCH_AGENT_MODEL", "qwen3:8b")
    assert isinstance(build_service("postgresql://unused").extractor, LangChainOllamaExtractor)
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("RESEARCH_AGENT_MODEL", "gpt-4.1-mini")
    assert isinstance(build_service("postgresql://unused").extractor, LangChainOpenAIExtractor)
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "freetoken")
    monkeypatch.setenv("RESEARCH_AGENT_MODEL", "Qwen3-30B-A3B")
    assert isinstance(
        build_service("postgresql://unused").extractor,
        LangChainFreeTokenExtractor,
    )


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="must be 'ollama', 'openai', or 'freetoken'"):
        build_service("postgresql://unused")


def test_freetoken_uses_a_provider_specific_default_model(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "freetoken")
    monkeypatch.delenv("RESEARCH_AGENT_MODEL", raising=False)
    config = ResearchAgentConfig.from_environment()
    assert config.model == "Qwen3-30B-A3B"


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("http://127.0.0.1:1919", "http://127.0.0.1:1919/v1"),
        ("http://127.0.0.1:1919/v1/", "http://127.0.0.1:1919/v1"),
        ("https://gpu.example.com/inference", "https://gpu.example.com/inference/v1"),
    ],
)
def test_freetoken_endpoint_normalization(configured, expected):
    assert normalize_openai_base_url(configured) == expected


def test_freetoken_endpoint_rejects_non_http_or_relative_urls():
    with pytest.raises(ValueError, match="absolute HTTP"):
        normalize_openai_base_url("localhost:1919")
    with pytest.raises(ValueError, match="absolute HTTP"):
        normalize_openai_base_url("file:///tmp/socket")


def test_freetoken_health_url_preserves_reverse_proxy_prefix():
    assert freetoken_health_url("https://gpu.example.com/inference/v1") == (
        "https://gpu.example.com/inference/health"
    )


def test_freetoken_readiness_requires_the_configured_model(monkeypatch):
    extractor = LangChainFreeTokenExtractor(ResearchAgentConfig(
        provider="freetoken",
        model="Qwen3-30B-A3B",
        freetoken_base_url="http://127.0.0.1:1919/v1",
    ))
    calls = []

    def response(url):
        calls.append(url)
        if url.endswith("/health"):
            return {"status": "ok"}
        return {"data": [{"id": "Qwen3-30B-A3B"}]}

    monkeypatch.setattr(extractor, "_request_json", response)
    extractor.check_ready()
    assert extractor._ready is True
    assert calls == [
        "http://127.0.0.1:1919/health",
        "http://127.0.0.1:1919/v1/models",
    ]


def test_freetoken_readiness_rejects_wrong_model_without_claiming_jobs(monkeypatch):
    extractor = LangChainFreeTokenExtractor(ResearchAgentConfig(
        provider="freetoken",
        model="Qwen3-30B-A3B",
    ))
    monkeypatch.setattr(
        extractor,
        "_request_json",
        lambda url: {"status": "ok"} if url.endswith("/health") else {
            "data": [{"id": "another-model"}]
        },
    )
    repository = FakeRepository(jobs=[job()])
    result = ResearchAgentService(
        repository, extractor, extractor.config
    ).process_queued(limit=1)
    assert result[0]["status"] == "UNAVAILABLE"
    assert result[0]["jobs_claimed"] == 0
    assert repository.claim_args is None


def test_freetoken_langchain_adapter_uses_tool_structured_output(monkeypatch):
    calls = {}

    class Structured:
        def invoke(self, messages):
            payload = __import__("json").loads(messages[1].content)
            chunk = payload["source_captures"][0]
            return BatchResearchExtraction(observations=[ProposedObservation(
                canonical_field="founder_name",
                proposed_value="Jane Doe",
                value_type="FACT",
                confidence="HIGH",
                source_capture_id=chunk["capture_id"],
                source_chunk_id=chunk["chunk_id"],
                evidence_excerpt="Founder Jane Doe leads the firm.",
            )])

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def with_structured_output(self, schema, **kwargs):
            calls["schema"] = schema
            calls["structured"] = kwargs
            return Structured()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    config = ResearchAgentConfig(
        provider="freetoken",
        model="Qwen3-30B-A3B",
        freetoken_base_url="http://127.0.0.1:1919",
        max_chunks=1,
        max_chunks_per_request=1,
    )
    extractor = LangChainFreeTokenExtractor(config)
    extractor._ready = True
    result = extractor.extract(
        firm_id="firm-1", dataset_version="ia-test", captures=[capture()]
    )
    assert result.observations[0].proposed_value == "Jane Doe"
    assert calls["init"]["base_url"] == "http://127.0.0.1:1919/v1"
    assert calls["structured"] == {"method": "function_calling", "strict": True}


def test_markdown_sections_are_chunked_with_stable_offsets_and_ids():
    source = capture(
        content=(
            "Navigation and legal notices.\n\n"
            "# About Our Firm\nFounder Jane Doe leads the advisory practice.\n\n"
            "# Services\nWe provide retirement planning and investment management."
        )
    )
    first = chunk_capture(source, 80)
    second = chunk_capture(source, 80)
    assert first == second
    assert all(len(item.content) <= 80 for item in first)
    assert all(source.content[item.start_char:item.end_char] == item.content for item in first)
    assert any(item.section_title == "About Our Firm" for item in first)


def test_relevant_sections_are_selected_before_generic_legal_text():
    source = capture(
        content=(
            "# Privacy\n" + "Generic legal notice. " * 20 + "\n"
            "# Leadership\nFounder Jane Doe is the managing principal.\n"
            "# Services\nFinancial planning and retirement services are offered."
        )
    )
    config = ResearchAgentConfig(max_chunk_chars=500, max_chunks=1, max_content_chars=500)
    selected = select_relevant_chunks([source], config)
    assert len(selected) == 1
    assert selected[0].section_title in {"Leadership", "Services"}
    assert "Generic legal notice" not in selected[0].content


def test_chunk_selection_preserves_source_coverage_when_budget_allows():
    sources = [
        capture("capture-1", "# About\nFounder Jane Doe."),
        capture("capture-2", "# Contact\nEmail jane@example.com."),
    ]
    selected = select_relevant_chunks(
        sources,
        ResearchAgentConfig(max_chunk_chars=500, max_chunks=2, max_content_chars=1000),
    )
    assert {item.capture_id for item in selected} == {"capture-1", "capture-2"}


def test_empty_capture_produces_no_chunks_and_fails_safely():
    empty = capture(content="   \n\n")
    assert chunk_capture(empty, 500) == []
    repository = FakeRepository(captures=[empty])
    result = ResearchAgentService(
        repository, FakeExtractor(), ResearchAgentConfig(max_chunk_chars=500)
    ).process_job(job())
    assert result["status"] == "FAILED"
    assert "no usable research sections" in result["error"]


def test_chunk_payload_retains_provenance_fields():
    selected = select_relevant_chunks([capture()], ResearchAgentConfig())
    payload = chunk_payload(selected)
    assert payload[0]["capture_id"] == "capture-1"
    assert payload[0]["chunk_id"] == selected[0].chunk_id
    assert payload[0]["content"] == selected[0].content


def test_unknown_chunk_is_rejected_even_when_capture_is_valid():
    extraction = ResearchExtraction(
        observations=[observation(source_chunk_id="chunk-invented")]
    )
    with pytest.raises(InvalidExtraction, match="unknown chunk"):
        validate_extraction(extraction, [capture()])


def test_chunk_must_belong_to_cited_capture():
    first = capture("capture-1")
    second = capture("capture-2", "Founder Jane Doe leads the firm.")
    second_chunk = chunk_capture(second, 6000)[0]
    extraction = ResearchExtraction(
        observations=[observation(source_chunk_id=second_chunk.chunk_id)]
    )
    with pytest.raises(InvalidExtraction, match="does not belong"):
        validate_extraction(extraction, [first, second], [*chunk_capture(first, 6000), second_chunk])


def test_single_capture_and_single_chunk_rebinds_both_opaque_ids():
    source = capture()
    source_chunk = chunk_capture(source, 6000)[0]
    extraction = ResearchExtraction(
        observations=[
            observation(source_capture_id="1", source_chunk_id="1")
        ]
    )
    rebound = normalize_single_capture_references(extraction, [source], [source_chunk])
    assert rebound.observations[0].source_capture_id == source.capture_id
    assert rebound.observations[0].source_chunk_id == source_chunk.chunk_id


def test_multiple_chunks_are_never_guessed_during_rebinding():
    source = capture(content="Founder Jane Doe. " * 100)
    chunks = chunk_capture(source, 500)
    extraction = ResearchExtraction(
        observations=[observation(source_capture_id="1", source_chunk_id="1")]
    )
    rebound = normalize_single_capture_references(extraction, [source], chunks)
    assert rebound.observations[0].source_capture_id == source.capture_id
    assert rebound.observations[0].source_chunk_id == "1"


def test_exact_excerpt_repairs_a_wrong_chunk_reference_without_guessing():
    source = capture(
        content="# Leadership\nJane Doe founded the firm.\n# Services\nRetirement planning."
    )
    chunks = chunk_capture(source, 500)
    leadership = next(item for item in chunks if item.section_title == "Leadership")
    extraction = ResearchExtraction(
        observations=[
            observation(
                source_capture_id="wrong-capture",
                source_chunk_id="wrong-chunk",
                evidence_excerpt="Jane Doe founded the firm.",
            )
        ]
    )
    repaired = normalize_exact_evidence_references(extraction, chunks)
    assert repaired.observations[0].source_capture_id == source.capture_id
    assert repaired.observations[0].source_chunk_id == leadership.chunk_id


def test_duplicate_excerpt_across_chunks_is_not_rebound_ambiguously():
    first = capture("first", "# Team\nJane Doe founded the firm.")
    second = capture("second", "# About\nJane Doe founded the firm.")
    chunks = [*chunk_capture(first, 500), *chunk_capture(second, 500)]
    extraction = ResearchExtraction(
        observations=[
            observation(
                source_capture_id="wrong-capture",
                source_chunk_id="wrong-chunk",
                evidence_excerpt="Jane Doe founded the firm.",
            )
        ]
    )
    unchanged = normalize_exact_evidence_references(extraction, chunks)
    assert unchanged.observations[0].source_capture_id == "wrong-capture"
    assert unchanged.observations[0].source_chunk_id == "wrong-chunk"


def test_transient_failure_is_requeued_with_bounded_backoff():
    repository = FakeRepository()
    service = ResearchAgentService(
        repository,
        FakeExtractor(error=TransientResearchAgentError("temporary timeout", "TIMEOUT")),
        ResearchAgentConfig(retry_base_seconds=2),
    )
    result = service.process_job(job())
    assert result["status"] == "RETRY_SCHEDULED"
    assert result["attempt"] == 1
    assert repository.statuses[-1][1] == "QUEUED"
    assert repository.statuses[-1][3]["error_category"] == "TIMEOUT"
    assert repository.statuses[-1][3]["next_attempt_at"] is not None


def test_transient_failure_stops_after_max_attempts():
    repository = FakeRepository()
    service = ResearchAgentService(
        repository,
        FakeExtractor(error=TransientResearchAgentError("temporary timeout", "TIMEOUT")),
        ResearchAgentConfig(),
    )
    exhausted = job()
    exhausted.update({"attempt_count": 3, "max_attempts": 3})
    result = service.process_job(exhausted)
    assert result["status"] == "FAILED"
    assert repository.statuses[-1][1] == "FAILED"


def test_permanent_provenance_failure_is_not_retried():
    repository = FakeRepository()
    extraction = ResearchExtraction(
        observations=[observation(source_chunk_id="invented")]
    )
    result = ResearchAgentService(
        repository, FakeExtractor(extraction), ResearchAgentConfig()
    ).process_job(job())
    assert result["status"] == "FAILED"
    assert repository.statuses[-1][1] == "FAILED"
    assert all(item[1] != "QUEUED" for item in repository.statuses)


def test_provider_error_classification_covers_timeout_rate_limit_and_credentials():
    assert classify_provider_error(TimeoutError("timed out"))[:2] == (
        "TRANSIENT_PROVIDER", True
    )
    assert classify_provider_error(RuntimeError("429 rate_limit_exceeded"))[:2] == (
        "RATE_LIMIT", True
    )
    assert classify_provider_error(RuntimeError("invalid_api_key"))[:2] == (
        "PROVIDER_CONFIGURATION", False
    )
    assert classify_provider_error(
        RuntimeError("OUTPUT_PARSING_FAILURE: failed to parse ResearchExtraction")
    )[:2] == ("MALFORMED_OUTPUT", True)


def test_process_queued_uses_a_bounded_worker_lease():
    repository = FakeRepository(jobs=[])
    service = ResearchAgentService(
        repository, FakeExtractor(), ResearchAgentConfig(lease_seconds=123)
    )
    assert service.process_queued(limit=2) == []
    assert repository.claim_args[0] == 2
    assert repository.claim_args[1].startswith("worker-")
    assert repository.claim_args[2] == 123


def test_worker_provides_a_distinct_attempt_number_to_retry_aware_extractors():
    class AttemptAwareExtractor(FakeExtractor):
        attempt_number = 1

    extractor = AttemptAwareExtractor()
    repository = FakeRepository()
    attempted = job()
    attempted["attempt_count"] = 2
    result = ResearchAgentService(
        repository, extractor, ResearchAgentConfig()
    ).process_job(attempted)
    assert result["status"] == "COMPLETED"
    assert extractor.attempt_number == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RESEARCH_AGENT_MAX_CHUNK_CHARS", "499"),
        ("RESEARCH_AGENT_MAX_CHUNKS", "0"),
        ("RESEARCH_AGENT_MAX_CHUNKS_PER_REQUEST", "9"),
        ("RESEARCH_AGENT_MAX_ATTEMPTS", "11"),
        ("RESEARCH_AGENT_LEASE_SECONDS", "29"),
        ("RESEARCH_AGENT_PROVIDER_HEALTH_TIMEOUT_SECONDS", "31"),
    ],
)
def test_invalid_worker_and_chunk_limits_are_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        ResearchAgentConfig.from_environment()


def test_cli_worker_accepts_database_url_fallback(monkeypatch):
    class FakeService:
        def process_queued(self, limit):
            return [{"limit": limit, "status": "ok"}]

    monkeypatch.delenv("PUBLISHER_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured-without-publisher-alias")
    monkeypatch.setattr("src.research_agent.build_service", lambda url: FakeService())
    result = CliRunner().invoke(app, ["research-agent-worker", "--limit", "2"])
    assert result.exit_code == 0
    assert '"limit": 2' in result.stdout


def test_cli_batch_queue_uses_bounded_service_operation(monkeypatch):
    class FakeService:
        def queue_priority_a_batch(self, **kwargs):
            return {"queued": kwargs["limit"], "dataset_version": kwargs["dataset_version"]}

    monkeypatch.setattr("src.research_agent.build_service", lambda url: FakeService())
    result = CliRunner().invoke(app, [
        "research-agent-queue-batch",
        "--database-url", "postgresql://unused",
        "--dataset-version", "ia-test",
        "--limit", "5",
    ])
    assert result.exit_code == 0
    assert '"queued": 5' in result.stdout


def test_repository_job_queries_keep_sql_placeholders_and_parameters_aligned(monkeypatch):
    class Result:
        def fetchone(self):
            return {"job_id": "job-1", "status": "QUEUED"}

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, query, params=()):
            assert query.count("%s") == len(params)
            return Result()

    repository = PostgresResearchAgentRepository("postgresql://unused")
    monkeypatch.setattr(repository, "_connect", lambda: Connection())
    queued = repository.queue_job(
        firm_id="firm-1",
        dataset_version="ia-test",
        captures=[capture()],
        config=ResearchAgentConfig(),
        requested_by="test",
    )
    assert queued["status"] == "QUEUED"
    assert repository.priority_a_batch_candidates("ia-test", 10) == []
    assert repository.next_jobs(1, worker_id="worker-test", lease_seconds=60) == []


def test_model_wall_clock_deadline_interrupts_a_streaming_request():
    with pytest.raises(TimeoutError, match="wall-clock timeout"):
        invoke_with_deadline(lambda: time.sleep(0.2), 0.02)


def test_model_wall_clock_deadline_returns_fast_results():
    assert invoke_with_deadline(lambda: "complete", 0.5) == "complete"
