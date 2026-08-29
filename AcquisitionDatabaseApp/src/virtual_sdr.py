"""Approval-gated virtual SDR workflow backed by LangGraph.

The graph consumes immutable SEC/Gold facts and accepted, source-linked research.
It creates versioned briefing artifacts but never sends outreach or mutates scoring.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, Sequence, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator


WORKFLOW_VERSION = "scm-virtual-sdr-v1"
PROMPT_VERSION = "scm-virtual-sdr-prompt-v1"
ALLOWED_DECISIONS = {"APPROVED", "REJECTED", "REVISION_REQUESTED"}


def configure_langsmith_privacy() -> None:
    """Trace execution metadata without exporting evidence, contacts, or drafts."""
    os.environ.setdefault("LANGSMITH_HIDE_INPUTS", "true")
    os.environ.setdefault("LANGSMITH_HIDE_OUTPUTS", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", "scm-virtual-sdr")


class CitedText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4_000)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class DecisionMaker(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    rationale: str = Field(min_length=1, max_length=1_000)
    source_ids: list[str] = Field(min_length=1, max_length=20)


class ObjectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objection: str = Field(min_length=1, max_length=800)
    response: str = Field(min_length=1, max_length=1_500)


class SdrBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executive_summary: CitedText
    acquisition_fit_thesis: CitedText
    decision_makers: list[DecisionMaker] = Field(default_factory=list, max_length=20)
    talking_points: list[CitedText] = Field(min_length=1, max_length=12)
    research_gaps: list[str] = Field(default_factory=list, max_length=20)
    email_subject: str = Field(min_length=1, max_length=200)
    email_body: str = Field(min_length=1, max_length=6_000)
    call_opener: str = Field(min_length=1, max_length=2_000)
    discovery_questions: list[str] = Field(min_length=3, max_length=12)
    likely_objections: list[ObjectionResponse] = Field(default_factory=list, max_length=10)
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    source_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("source_ids")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class QualityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["PASSED", "FAILED"]
    checks: dict[str, bool]
    unsupported_source_ids: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class SdrState(TypedDict, total=False):
    run_id: str
    firm_id: str
    dataset_version: str
    input_hash: str
    requested_by: str | None
    context: dict[str, Any]
    accepted_source_ids: list[str]
    research_gaps: list[str]
    identity_conflicts: list[str]
    firm_evidence: list[dict[str, Any]]
    decision_maker_evidence: list[dict[str, Any]]
    acquisition_signals: dict[str, Any]
    brief: dict[str, Any]
    artifact_id: str
    artifact_version: int
    quality: dict[str, Any]
    review: dict[str, Any]
    status: str
    error_message: str | None


class SdrRepository(Protocol):
    def load_context(self, firm_id: str, dataset_version: str) -> dict[str, Any]: ...
    def set_run_status(self, run_id: str, status: str, error_message: str | None = None) -> None: ...
    def save_artifact(
        self, run_id: str, brief: SdrBrief, quality: QualityResult, version: int
    ) -> dict[str, Any]: ...
    def finalize(self, run_id: str, artifact_id: str, decision: str) -> None: ...


class SdrBriefGenerator(Protocol):
    provider: str
    model_name: str

    def generate(self, context: dict[str, Any], research_gaps: Sequence[str]) -> SdrBrief: ...
    def revise(self, brief: SdrBrief, notes: str) -> SdrBrief: ...


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=_json_default, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sanitized_trace_metadata(state: SdrState) -> dict[str, Any]:
    """Return only identifiers and counts safe for observability metadata."""
    context = state.get("context") or {}
    return {
        "run_id": state.get("run_id"),
        "firm_id": state.get("firm_id"),
        "dataset_version": state.get("dataset_version"),
        "workflow_version": WORKFLOW_VERSION,
        "prompt_version": PROMPT_VERSION,
        "accepted_fact_count": len(context.get("accepted_observations") or []),
        "official_principal_count": len(context.get("official_principals") or []),
        "verified_contact_count": len(context.get("verified_contacts") or []),
    }


def collect_source_ids(context: dict[str, Any]) -> list[str]:
    ids = {
        f"sec:{context['dataset_version']}:firm_facts",
        f"gold:{context['dataset_version']}:firm_scores",
    }
    ids.update(
        str(item["source_id"])
        for item in context.get("accepted_observations", [])
        if item.get("source_id")
    )
    ids.update(
        str(item["source_id"])
        for item in context.get("official_principals", [])
        if item.get("source_id")
    )
    ids.update(
        str(item["source_id"])
        for item in context.get("verified_contacts", [])
        if item.get("source_id")
    )
    return sorted(ids)


def identify_conflicts(context: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    founders = {
        str(item.get("proposed_value", "")).strip().casefold()
        for item in context.get("accepted_observations", [])
        if item.get("canonical_field") == "founder_name" and item.get("proposed_value")
    }
    if len(founders) > 1:
        conflicts.append("Accepted sources identify different founders.")
    identity_fields = {"founder_name", "principal_name", "contact_name"}
    conflicting = [
        item for item in context.get("open_observations", [])
        if item.get("review_status") == "CONFLICTING"
        and item.get("canonical_field") in identity_fields
    ]
    if conflicting:
        conflicts.append(f"{len(conflicting)} unresolved research observation(s) are conflicting.")
    return conflicts


def identify_gaps(context: dict[str, Any]) -> list[str]:
    fields = {
        item.get("canonical_field")
        for item in context.get("accepted_observations", [])
    }
    gaps: list[str] = []
    if "founder_name" not in fields and not context.get("official_principals"):
        gaps.append("Founder or principal identity is not verified.")
    if not ({"ownership_summary", "ownership_language"} & fields):
        gaps.append("Ownership interpretation is not verified.")
    if not ({"services_summary", "client_focus"} & fields):
        gaps.append("Services and client focus require additional evidence.")
    if not context.get("verified_contacts"):
        gaps.append("No verified outreach contact is available.")
    non_identity_conflicts = [
        item for item in context.get("open_observations", [])
        if item.get("review_status") == "CONFLICTING"
        and item.get("canonical_field") not in {"founder_name", "principal_name", "contact_name"}
    ]
    if non_identity_conflicts:
        gaps.append(f"{len(non_identity_conflicts)} non-identity research conflict(s) remain unresolved.")
    return gaps


def validate_brief_sources(brief: SdrBrief, allowed_source_ids: Sequence[str]) -> QualityResult:
    allowed = set(allowed_source_ids)
    cited = set(brief.source_ids)
    cited.update(brief.executive_summary.source_ids)
    cited.update(brief.acquisition_fit_thesis.source_ids)
    for item in brief.decision_makers:
        cited.update(item.source_ids)
    for item in brief.talking_points:
        cited.update(item.source_ids)
    unsupported = sorted(cited - allowed)
    checks = {
        "citations_present": bool(cited),
        "citations_allowed": not unsupported,
        "discovery_questions_complete": len(brief.discovery_questions) >= 3,
        "email_complete": bool(brief.email_subject.strip() and brief.email_body.strip()),
        "call_preparation_complete": bool(brief.call_opener.strip()),
        "outbound_action_absent": True,
    }
    issues = []
    if unsupported:
        issues.append("Brief cites sources outside the accepted evidence set.")
    if not all(checks.values()):
        issues.append("One or more briefing completeness checks failed.")
    return QualityResult(
        status="PASSED" if all(checks.values()) else "FAILED",
        checks=checks,
        unsupported_source_ids=unsupported,
        issues=issues,
    )


def _brief_system_prompt() -> str:
    return (
        "You prepare internal meeting briefs for acquisition discussions with registered "
        "investment advisers. Use only the supplied accepted facts and official SEC/Gold "
        "facts. Every factual narrative and talking point must cite one or more supplied "
        "source_ids. Never invent a person, contact method, ownership conclusion, age, sale "
        "intent, succession conclusion, or regulatory fact. Treat unresolved items as "
        "research gaps. Draft an email and call preparation, but do not claim that anything "
        "was sent and do not recommend changing scores or priorities. Keep the tone discreet, "
        "professional, and suitable for CEO review."
    )


class LangChainSdrGenerator:
    def __init__(self) -> None:
        configure_langsmith_privacy()
        self.provider = os.getenv("VIRTUAL_SDR_PROVIDER", "openai").strip().lower()
        defaults = {"openai": "gpt-4.1-mini", "ollama": "qwen3:8b", "freetoken": "Qwen3-30B-A3B"}
        self.model_name = os.getenv("VIRTUAL_SDR_MODEL", defaults.get(self.provider, "gpt-4.1-mini"))
        self.timeout = int(os.getenv("VIRTUAL_SDR_TIMEOUT_SECONDS", "120"))
        self.max_tokens = int(os.getenv("VIRTUAL_SDR_MAX_TOKENS", "4000"))

    def _model(self):
        if self.provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=self.model_name,
                base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
                temperature=0,
                reasoning=False,
                num_predict=self.max_tokens,
                client_kwargs={"timeout": self.timeout},
            ).with_structured_output(SdrBrief)
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "temperature": 0,
            "timeout": self.timeout,
            "max_retries": 2,
            "max_tokens": self.max_tokens,
        }
        if self.provider == "freetoken":
            base_url = os.environ["FREETOKEN_BASE_URL"].rstrip("/")
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            kwargs.update(
                base_url=base_url,
                api_key=os.getenv("FREETOKEN_API_KEY", "freetoken-local"),
            )
        elif self.provider != "openai":
            raise ValueError("VIRTUAL_SDR_PROVIDER must be openai, ollama, or freetoken")
        return ChatOpenAI(**kwargs).with_structured_output(
            SdrBrief, method="json_schema", strict=True
        )

    def generate(self, context: dict[str, Any], research_gaps: Sequence[str]) -> SdrBrief:
        from langchain_core.messages import HumanMessage, SystemMessage

        safe_context = {
            "firm": context.get("firm"),
            "facts": context.get("facts"),
            "scores": context.get("scores"),
            "accepted_observations": context.get("accepted_observations"),
            "official_principals": context.get("official_principals"),
            "verified_contacts": context.get("verified_contacts"),
            "allowed_source_ids": collect_source_ids(context),
            "research_gaps": list(research_gaps),
        }
        result = self._model().invoke([
            SystemMessage(content=_brief_system_prompt()),
            HumanMessage(content=json.dumps(safe_context, default=_json_default)),
        ])
        return result if isinstance(result, SdrBrief) else SdrBrief.model_validate(result)

    def revise(self, brief: SdrBrief, notes: str) -> SdrBrief:
        from langchain_core.messages import HumanMessage, SystemMessage

        result = self._model().invoke([
            SystemMessage(content=_brief_system_prompt()),
            HumanMessage(content=json.dumps({
                "current_brief": brief.model_dump(),
                "review_notes": notes[:4_000],
                "instruction": "Revise only as requested. Preserve all source IDs and do not add facts.",
            })),
        ])
        return result if isinstance(result, SdrBrief) else SdrBrief.model_validate(result)


@dataclass(frozen=True)
class R2ArtifactStore:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    session_token: str | None = None

    @classmethod
    def from_environment(cls) -> "R2ArtifactStore | None":
        values = [
            os.getenv("CLOUDFLARE_R2_ACCOUNT_ID"),
            os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID"),
            os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY"),
            os.getenv("CLOUDFLARE_R2_BUCKET"),
        ]
        if not all(values):
            return None
        return cls(*[str(value) for value in values], os.getenv("CLOUDFLARE_R2_SESSION_TOKEN"))

    def put(self, key: str, payload: bytes) -> dict[str, str]:
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            aws_session_token=self.session_token,
            region_name="auto",
        )
        response = client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
            Metadata={"sha256": hashlib.sha256(payload).hexdigest()},
        )
        return {"key": key, "etag": str(response.get("ETag", "")).strip('"')}


class PostgresSdrRepository:
    def __init__(self, database_url: str, artifact_store: R2ArtifactStore | None = None):
        self.database_url = database_url
        self.artifact_store = artifact_store

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url)

    def load_context(self, firm_id: str, dataset_version: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM firms WHERE firm_id=%s AND dataset_version=%s", (firm_id, dataset_version))
            firm = cursor.fetchone()
            columns = [item.name for item in cursor.description] if cursor.description else []
            firm_row = dict(zip(columns, firm)) if firm else None
            if not firm_row:
                raise ValueError("Firm not found for requested dataset version")
            cursor.execute("SELECT * FROM firm_facts WHERE firm_id=%s AND dataset_version=%s", (firm_id, dataset_version))
            row = cursor.fetchone(); columns = [item.name for item in cursor.description] if cursor.description else []
            facts = dict(zip(columns, row)) if row else {}
            cursor.execute("SELECT * FROM firm_scores WHERE firm_id=%s AND dataset_version=%s", (firm_id, dataset_version))
            row = cursor.fetchone(); columns = [item.name for item in cursor.description] if cursor.description else []
            scores = dict(zip(columns, row)) if row else {}
            cursor.execute(
                """SELECT o.canonical_field,o.proposed_value,o.value_type,o.confidence,
                          o.evidence_excerpt,o.source_id,s.source_url,s.source_title,s.content_hash
                     FROM research_observations o JOIN research_sources s USING(source_id)
                    WHERE o.firm_id=%s AND o.dataset_version=%s AND o.review_status='ACCEPTED'
                    ORDER BY o.canonical_field,o.reviewed_at,o.observation_id LIMIT 100""",
                (firm_id, dataset_version),
            )
            accepted = [dict(zip([item.name for item in cursor.description], row)) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT canonical_field,proposed_value,review_status,source_id
                     FROM research_observations
                    WHERE firm_id=%s AND dataset_version=%s AND review_status IN ('PROPOSED','CONFLICTING')
                    ORDER BY created_at DESC LIMIT 100""",
                (firm_id, dataset_version),
            )
            open_observations = [dict(zip([item.name for item in cursor.description], row)) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT full_legal_name,title_status,principal_type,source_url,
                          ('iapd-principal:' || principal_id) AS source_id
                     FROM iapd_firm_principals WHERE firm_id=%s
                      AND filing_date IS NOT DISTINCT FROM (
                        SELECT max(filing_date) FROM iapd_firm_principals WHERE firm_id=%s
                      )
                    ORDER BY full_legal_name LIMIT 100""",
                (firm_id, firm_id),
            )
            principals = [dict(zip([item.name for item in cursor.description], row)) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT contact_name,title,email,phone,profile_url,
                          ('contact:' || contact_id) AS source_id
                     FROM contacts WHERE firm_id=%s AND dataset_version=%s
                      AND verification_status='VERIFIED' ORDER BY contact_name LIMIT 50""",
                (firm_id, dataset_version),
            )
            contacts = [dict(zip([item.name for item in cursor.description], row)) for row in cursor.fetchall()]
        return {
            "firm_id": firm_id,
            "dataset_version": dataset_version,
            "firm": firm_row,
            "facts": facts,
            "scores": scores,
            "accepted_observations": accepted,
            "open_observations": open_observations,
            "official_principals": principals,
            "verified_contacts": contacts,
        }

    def set_run_status(self, run_id: str, status: str, error_message: str | None = None) -> None:
        terminal = status in {"APPROVED", "REJECTED", "FAILED", "RESEARCH_REQUIRED", "NEEDS_REVIEW"}
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE virtual_sdr_runs SET status=%s,error_message=%s,
                          started_at=COALESCE(started_at,now()),
                          completed_at=CASE WHEN %s THEN now() ELSE completed_at END,updated_at=now()
                     WHERE run_id=%s""",
                (status, error_message, terminal, run_id),
            )

    def save_artifact(self, run_id: str, brief: SdrBrief, quality: QualityResult, version: int) -> dict[str, Any]:
        artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:artifact:{version}"))
        payload = json.dumps(brief.model_dump(), sort_keys=True).encode("utf-8")
        r2_key = r2_etag = None
        storage_error = None
        if self.artifact_store:
            try:
                stored = self.artifact_store.put(f"virtual-sdr/{run_id}/brief-v{version}.json", payload)
                r2_key, r2_etag = stored["key"], stored["etag"]
            except Exception as exc:  # PostgreSQL remains canonical when R2 is unavailable.
                storage_error = type(exc).__name__
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE virtual_sdr_artifacts SET status='SUPERSEDED',updated_at=now() WHERE run_id=%s AND version<>%s AND status='DRAFT'",
                (run_id, version),
            )
            cursor.execute(
                """INSERT INTO virtual_sdr_artifacts
                       (artifact_id,run_id,version,status,content,source_ids,confidence,quality_status,
                        r2_key,r2_etag,storage_error,created_at,updated_at)
                     VALUES (%s,%s,%s,'DRAFT',%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,now(),now())
                     ON CONFLICT (run_id,version) DO UPDATE SET content=EXCLUDED.content,
                       source_ids=EXCLUDED.source_ids,confidence=EXCLUDED.confidence,
                       quality_status=EXCLUDED.quality_status,r2_key=EXCLUDED.r2_key,
                       r2_etag=EXCLUDED.r2_etag,storage_error=EXCLUDED.storage_error,updated_at=now()
                     RETURNING artifact_id""",
                (artifact_id, run_id, version, payload.decode(), json.dumps(brief.source_ids),
                 brief.confidence, quality.status, r2_key, r2_etag, storage_error),
            )
            artifact_id = str(cursor.fetchone()[0])
            cursor.execute(
                """INSERT INTO virtual_sdr_quality_checks
                       (check_id,run_id,artifact_id,check_type,status,score,details,created_at)
                     VALUES (%s,%s,%s,'DETERMINISTIC_GATE',%s,%s,%s::jsonb,now())
                     ON CONFLICT (run_id,artifact_id,check_type) DO UPDATE SET
                       status=EXCLUDED.status,score=EXCLUDED.score,details=EXCLUDED.details""",
                (str(uuid.uuid5(uuid.NAMESPACE_URL, f"{artifact_id}:quality")), run_id, artifact_id,
                 quality.status, 1.0 if quality.status == "PASSED" else 0.0,
                 quality.model_dump_json()),
            )
            cursor.execute(
                "UPDATE virtual_sdr_runs SET latest_artifact_id=%s,status='AWAITING_APPROVAL',updated_at=now() WHERE run_id=%s",
                (artifact_id, run_id),
            )
            cursor.execute(
                "UPDATE virtual_sdr_reviews SET resume_status='COMPLETED',updated_at=now() WHERE run_id=%s AND resume_status='SUBMITTED'",
                (run_id,),
            )
        return {"artifact_id": artifact_id, "r2_key": r2_key, "storage_error": storage_error}

    def finalize(self, run_id: str, artifact_id: str, decision: str) -> None:
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("Only approved or rejected artifacts can be finalized")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE virtual_sdr_artifacts SET status=%s,updated_at=now() WHERE artifact_id=%s AND run_id=%s",
                (decision, artifact_id, run_id),
            )
            cursor.execute(
                "UPDATE virtual_sdr_runs SET status=%s,completed_at=now(),updated_at=now() WHERE run_id=%s",
                (decision, run_id),
            )
            cursor.execute(
                "UPDATE virtual_sdr_reviews SET resume_status='COMPLETED',updated_at=now() WHERE run_id=%s AND resume_status='SUBMITTED'",
                (run_id,),
            )


def build_virtual_sdr_graph(
    repository: SdrRepository, generator: SdrBriefGenerator, *, checkpointer: Any = None
):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    def load_context(state: SdrState) -> SdrState:
        repository.set_run_status(state["run_id"], "RUNNING")
        context = repository.load_context(state["firm_id"], state["dataset_version"])
        return {"context": context, "accepted_source_ids": collect_source_ids(context)}

    def evidence_gate(state: SdrState) -> SdrState:
        context = state["context"]
        has_external_evidence = bool(
            context.get("accepted_observations")
            or context.get("official_principals")
            or context.get("verified_contacts")
        )
        if not has_external_evidence:
            repository.set_run_status(state["run_id"], "RESEARCH_REQUIRED", "No accepted external evidence is available")
            return {"status": "RESEARCH_REQUIRED", "research_gaps": identify_gaps(context)}
        return {"status": "EVIDENCE_READY"}

    def conflict_gate(state: SdrState) -> SdrState:
        conflicts = identify_conflicts(state["context"])
        if conflicts:
            repository.set_run_status(state["run_id"], "NEEDS_REVIEW", "; ".join(conflicts))
            return {"status": "NEEDS_REVIEW", "identity_conflicts": conflicts}
        return {"status": "VERIFIED", "identity_conflicts": []}

    def research_firm(state: SdrState) -> SdrState:
        observations = [
            item for item in state["context"].get("accepted_observations", [])
            if item.get("canonical_field") not in {"founder_name", "principal_name", "contact_name", "contact_email", "contact_phone"}
        ]
        return {"firm_evidence": observations}

    def research_decision_makers(state: SdrState) -> SdrState:
        context = state["context"]
        people = [
            item for item in context.get("accepted_observations", [])
            if item.get("canonical_field") in {"founder_name", "principal_name", "contact_name", "contact_email", "contact_phone"}
        ]
        people.extend(context.get("official_principals", []))
        people.extend(context.get("verified_contacts", []))
        return {"decision_maker_evidence": people}

    def acquisition_context(state: SdrState) -> SdrState:
        context = state["context"]
        return {"acquisition_signals": {
            "acquisition_score": context.get("scores", {}).get("acquisition_score"),
            "priority_category": context.get("scores", {}).get("priority_category"),
            "component_scores": context.get("scores", {}).get("component_scores"),
            "reason_codes": context.get("scores", {}).get("reason_codes"),
            "total_aum": context.get("facts", {}).get("total_aum"),
            "employee_count": context.get("facts", {}).get("employee_count"),
        }}

    def gaps(state: SdrState) -> SdrState:
        return {"research_gaps": identify_gaps(state["context"])}

    def draft(state: SdrState) -> SdrState:
        try:
            brief = generator.generate(state["context"], state.get("research_gaps", []))
            return {"brief": brief.model_dump(), "artifact_version": 1, "status": "DRAFTED"}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:1_000]
            repository.set_run_status(state["run_id"], "FAILED", message)
            return {"status": "FAILED", "error_message": message}

    def quality_gate(state: SdrState) -> SdrState:
        brief = SdrBrief.model_validate(state["brief"])
        quality = validate_brief_sources(brief, state["accepted_source_ids"])
        if quality.status == "FAILED":
            repository.set_run_status(state["run_id"], "FAILED", "; ".join(quality.issues))
        return {"quality": quality.model_dump(), "status": quality.status}

    def persist(state: SdrState) -> SdrState:
        try:
            saved = repository.save_artifact(
                state["run_id"], SdrBrief.model_validate(state["brief"]),
                QualityResult.model_validate(state["quality"]), state["artifact_version"],
            )
            return {"artifact_id": saved["artifact_id"], "status": "AWAITING_APPROVAL"}
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:1_000]
            repository.set_run_status(state["run_id"], "FAILED", message)
            return {"status": "FAILED", "error_message": message}

    def approval(state: SdrState) -> SdrState:
        decision = interrupt({
            "type": "CEO_BRIEF_REVIEW",
            "run_id": state["run_id"],
            "artifact_id": state["artifact_id"],
            "allowed_decisions": sorted(ALLOWED_DECISIONS),
        })
        normalized = str((decision or {}).get("decision", "")).upper()
        if normalized not in ALLOWED_DECISIONS:
            raise ValueError("Invalid SDR review decision")
        if normalized == "APPROVED" and (decision or {}).get("edited_brief"):
            normalized = "APPROVED_EDITED"
        return {"review": decision, "status": normalized}

    def apply_approved_edit(state: SdrState) -> SdrState:
        edited = SdrBrief.model_validate(state["review"]["edited_brief"])
        quality = validate_brief_sources(edited, state["accepted_source_ids"])
        if quality.status == "FAILED":
            repository.set_run_status(state["run_id"], "FAILED", "; ".join(quality.issues))
            return {"quality": quality.model_dump(), "status": "FAILED"}
        version = int(state.get("artifact_version", 1)) + 1
        saved = repository.save_artifact(state["run_id"], edited, quality, version)
        return {
            "brief": edited.model_dump(), "quality": quality.model_dump(),
            "artifact_id": saved["artifact_id"], "artifact_version": version,
            "status": "APPROVED",
        }

    def revise(state: SdrState) -> SdrState:
        try:
            review = state["review"]
            current = SdrBrief.model_validate(review.get("edited_brief") or state["brief"])
            revised = generator.revise(current, str(review.get("notes") or ""))
            return {
                "brief": revised.model_dump(),
                "artifact_version": int(state.get("artifact_version", 1)) + 1,
                "status": "REVISED",
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"[:1_000]
            repository.set_run_status(state["run_id"], "FAILED", message)
            return {"status": "FAILED", "error_message": message}

    def finalize(state: SdrState) -> SdrState:
        decision = state["status"]
        repository.finalize(state["run_id"], state["artifact_id"], decision)
        return {"status": decision}

    builder = StateGraph(SdrState)
    builder.add_node("load_context", load_context)
    builder.add_node("check_accepted_evidence", evidence_gate)
    builder.add_node("cross_check_identities", conflict_gate)
    builder.add_node("research_firm", research_firm)
    builder.add_node("research_decision_makers", research_decision_makers)
    builder.add_node("build_acquisition_context", acquisition_context)
    builder.add_node("identify_gaps", gaps)
    builder.add_node("generate_brief", draft)
    builder.add_node("quality_gate", quality_gate)
    builder.add_node("persist_artifact", persist)
    builder.add_node("human_approval", approval)
    builder.add_node("apply_approved_edit", apply_approved_edit)
    builder.add_node("revise_brief", revise)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "check_accepted_evidence")
    builder.add_conditional_edges("check_accepted_evidence", lambda state: state["status"], {
        "RESEARCH_REQUIRED": END, "EVIDENCE_READY": "cross_check_identities",
    })
    builder.add_conditional_edges("cross_check_identities", lambda state: state["status"], {
        "NEEDS_REVIEW": END, "VERIFIED": "research_firm",
    })
    builder.add_edge("research_firm", "research_decision_makers")
    builder.add_edge("research_decision_makers", "identify_gaps")
    builder.add_edge("identify_gaps", "build_acquisition_context")
    builder.add_edge("build_acquisition_context", "generate_brief")
    builder.add_conditional_edges("generate_brief", lambda state: state["status"], {
        "DRAFTED": "quality_gate", "FAILED": END,
    })
    builder.add_conditional_edges("quality_gate", lambda state: state["status"], {
        "FAILED": END, "PASSED": "persist_artifact",
    })
    builder.add_conditional_edges("persist_artifact", lambda state: state["status"], {
        "AWAITING_APPROVAL": "human_approval", "FAILED": END,
    })
    builder.add_conditional_edges("human_approval", lambda state: state["status"], {
        "APPROVED": "finalize", "APPROVED_EDITED": "apply_approved_edit",
        "REJECTED": "finalize", "REVISION_REQUESTED": "revise_brief",
    })
    builder.add_conditional_edges("apply_approved_edit", lambda state: state["status"], {
        "APPROVED": "finalize", "FAILED": END,
    })
    builder.add_conditional_edges("revise_brief", lambda state: state["status"], {
        "REVISED": "quality_gate", "FAILED": END,
    })
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def _deployment_graph():
    configure_langsmith_privacy()
    database_url = os.getenv("DATABASE_URL") or os.getenv("PUBLISHER_DATABASE_URL")
    if not database_url:
        # Import remains safe for tests/build tooling; execution reports configuration clearly.
        class MissingRepository:
            def __getattr__(self, _name):
                raise RuntimeError("DATABASE_URL is required for virtual SDR execution")
        repository: Any = MissingRepository()
    else:
        repository = PostgresSdrRepository(database_url, R2ArtifactStore.from_environment())
    return build_virtual_sdr_graph(repository, LangChainSdrGenerator())


graph = _deployment_graph()
