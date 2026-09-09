"""Resumable, bounded extraction of Schedule D 5.K.(3) custodian facts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from src.adv_facts import stable_custodian_id, validate_pdf

OCR_VERSION = "scm-adv-ocr-v2"
EXTRACTION_VERSION = "scm-adv-custodian-v2"
USER_AGENT = "SCM-RIA-Research/1.0 contact: operations@standishcapital.com"
ACTIVE_JOB_STATUSES = ("QUEUED", "RUNNING", "RETRY_WAIT")
US_STATES = ("Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut","Delaware","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa","Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan","Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada","New Hampshire","New Jersey","New Mexico","New York","North Carolina","North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont","Virginia","Washington","West Virginia","Wisconsin","Wyoming","District of Columbia")


class AdvUnavailableError(RuntimeError):
    pass


class AdvTransientError(RuntimeError):
    pass


@dataclass(frozen=True)
class CustodianCandidate:
    legal_name: str
    primary_business_name: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    related_person: bool | None = None
    broker_dealer_sec_number: str | None = None
    legal_entity_identifier: str | None = None
    sma_aum: float | None = None
    source_page: int | None = None


class RequestRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1.0 / max(requests_per_second, 0.1)
        self.lock = threading.Lock()
        self.next_request_at = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_request_at - now)
            self.next_request_at = max(now, self.next_request_at) + self.interval
        if delay:
            time.sleep(delay)


def preflight() -> None:
    missing = [name for name in ("pdftoppm", "pdfinfo", "tesseract") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"Local ADV OCR unavailable; install: {', '.join(missing)}")


def _native_pdftotext() -> str | None:
    """Locate Poppler's text extractor when the runtime PATH exposes wrappers."""
    direct = shutil.which("pdftotext")
    if direct:
        return direct
    info = shutil.which("pdfinfo")
    if not info:
        return None
    candidate = Path(info).parents[2] / "native" / "poppler" / "poppler" / "bin" / "pdftotext"
    return str(candidate) if candidate.exists() else None


def _embedded_text(pdf: Path, pages: int) -> str | None:
    command = _native_pdftotext()
    if not command:
        return None
    result = subprocess.run([command, "-layout", str(pdf), "-"], check=False, capture_output=True, text=True)
    if result.returncode or not result.stdout.strip():
        return None
    labeled = []
    for index, page in enumerate(result.stdout.split("\f"), 1):
        if page.strip():
            labeled.append(f"\n--- PAGE {index} ---\n{page}")
    text = "".join(labeled)
    return text if re.search(r"\(a\)\s*Legal name of custodian", text, re.I) else None


def _field(block: str, label: str, next_label: str | None = None) -> str | None:
    flexible = lambda value: r"\s+".join(re.escape(part) for part in value.split())
    end = rf"(?={flexible(next_label)}|$)" if next_label else "$"
    match = re.search(rf"{flexible(label)}\s*:?\s*(.+?){end}", block, re.I | re.S)
    return " ".join(match.group(1).split()).strip() if match else None


def _location(block: str) -> tuple[str | None, str | None, str | None]:
    match = re.search(r"City\s*:\s*(.+?)\s+State\s*:\s*(.+?)\s+Country\s*:\s*(.+?)(?=\s+(?:Yes\s+No|\(d\))|$)", block, re.I | re.S)
    if match and all(value.strip() for value in match.groups()) and not match.group(1).strip().lower().startswith("state"):
        return tuple(" ".join(value.split()) for value in match.groups())  # type: ignore[return-value]
    lines = block.splitlines()
    for index, line in enumerate(lines[:-1]):
        if all(label in line.lower() for label in ("city:", "state:", "country:")):
            values = next((candidate.strip() for candidate in lines[index + 1:] if candidate.strip()), "")
            columns = [value.strip() for value in re.split(r"\s{2,}", values) if value.strip()]
            if len(columns) >= 3:
                return columns[0], columns[1], " ".join(columns[2:])
    match = re.search(r"City\s*:\s*State\s*:\s*Country\s*:\s*(.+?)(?=\s+(?:Yes\s+No|\(d\))|$)", block, re.I | re.S)
    if not match:
        return None, None, None
    value = " ".join(match.group(1).split())
    for state in sorted(US_STATES, key=len, reverse=True):
        state_match = re.search(rf"\b{re.escape(state)}\b", value, re.I)
        if state_match:
            return value[:state_match.start()].strip(" ,") or None, state, value[state_match.end():].strip(" ,") or None
    return None, None, value or None


def _source_page(text: str, position: int) -> int | None:
    matches = list(re.finditer(r"---\s*PAGE\s+(\d+)\s*---", text[:position], re.I))
    return int(matches[-1].group(1)) if matches else None


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"---\s*PAGE\s+\d+\s*---", " ", value, flags=re.I)
    value = " ".join(value.split()).strip(" :;,-")
    if len(value) > 250 or "primary business name of custodian" in value.lower():
        return None
    return value or None


def parse_custodians(text: str) -> list[CustodianCandidate]:
    marker = re.search(r"(?:SECTION\s+)?5\.K\.\(3\).*?(?=\(a\)\s*Legal name of custodian)", text, re.I | re.S)
    offset = marker.start() if marker else 0
    relevant = text[offset:]
    starts = list(re.finditer(r"(?=\(a\)\s*Legal name of custodian)", relevant, re.I))
    result: list[CustodianCandidate] = []
    seen: set[tuple[str, float | None]] = set()
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(relevant)
        block = relevant[start.start():end]
        block = re.split(r"(?=SECTION\s+(?!5\.K\.\(3\))|Item\s+6\b)", block, maxsplit=1, flags=re.I)[0]
        legal = _clean_name(_field(block, "(a) Legal name of custodian", "(b) Primary business name of custodian"))
        if not legal:
            continue
        business = _clean_name(_field(block, "(b) Primary business name of custodian", "(c)"))
        city, state, country = _location(block)
        sec = re.search(r"SEC registration number.*?([0-9]+\s*-\s*[0-9]+)", block, re.I | re.S)
        lei = re.search(r"legal entity identifier.*?\b([A-Z0-9]{18,20})\b", block, re.I | re.S)
        amount = re.search(r"amount.*?held at the custodian.*?\$\s*([0-9,]+(?:\.\d+)?)", block, re.I | re.S)
        aum = float(amount.group(1).replace(",", "")) if amount else None
        key = (legal.casefold(), aum)
        if key in seen:
            continue
        seen.add(key)
        result.append(CustodianCandidate(legal, business, city, state, country, None, sec.group(1).replace(" ", "") if sec else None, lei.group(1) if lei else None, aum, _source_page(text, offset + start.start())))
    return result


def _ocr_pdf(payload: bytes, max_pages: int | None = None, dpi: int = 180) -> tuple[str, int]:
    preflight()
    with tempfile.TemporaryDirectory(prefix="scm-adv-") as directory:
        root = Path(directory)
        pdf = root / "adv.pdf"
        pdf.write_bytes(payload)
        info = subprocess.run(["pdfinfo", str(pdf)], check=True, capture_output=True, text=True).stdout
        page_match = re.search(r"^Pages:\s+(\d+)", info, re.M)
        pages = int(page_match.group(1)) if page_match else 0
        if pages < 1:
            raise ValueError("ADV PDF contains no readable pages")
        embedded = _embedded_text(pdf, pages)
        if embedded:
            return embedded, pages
        max_pages = max_pages or int(os.getenv("ADV_OCR_MAX_PAGES", "250"))
        if pages > max_pages:
            raise ValueError(f"Image-only ADV PDF page count {pages} exceeds the OCR limit {max_pages}")
        output = []
        for index in range(1, pages + 1):
            prefix = root / f"page-{index}"
            image = prefix.with_suffix(".png")
            subprocess.run(["pdftoppm", "-png", "-singlefile", "-f", str(index), "-l", str(index), "-r", str(dpi), str(pdf), str(prefix)], check=True, capture_output=True)
            page = subprocess.run(["tesseract", str(image), "stdout", "--psm", "6"], check=True, capture_output=True, text=True).stdout
            output.append(f"\n--- PAGE {index} ---\n{page}")
            image.unlink(missing_ok=True)
        return "".join(output), pages


def _grounded(candidate: CustodianCandidate, text: str) -> bool:
    plain_text = re.sub(r"[^a-z0-9]", "", text.casefold())
    plain_name = re.sub(r"[^a-z0-9]", "", candidate.legal_name.casefold())
    if len(plain_name) < 4 or plain_name not in plain_text:
        return False
    return candidate.sma_aum is None or str(int(candidate.sma_aum)) in re.sub(r"\D", "", text)


def _auto_accept(candidate: CustodianCandidate, text: str, method: str) -> tuple[bool, str]:
    """Accept only a source-located row with an explicit legal name and SMA amount."""
    if not _grounded(candidate, text):
        return False, "candidate is not grounded in the extracted filing text"
    if candidate.source_page is None:
        return False, "source page is unavailable"
    if candidate.sma_aum is None or candidate.sma_aum < 0:
        return False, "reported SMA amount is unavailable or invalid"
    if method not in {"DETERMINISTIC_OCR", "LANGCHAIN_GROUNDED_FALLBACK"}:
        return False, "unsupported extraction method"
    return True, "PDF validated, CRD matched, source page located, and legal name/AUM grounded"


def parse_custodians_with_langchain(text: str) -> list[CustodianCandidate]:
    """Optional provider-neutral fallback; every candidate must be OCR-grounded."""
    if os.getenv("ADV_CUSTODIAN_LANGCHAIN_ENABLED", "false").lower() != "true":
        return []
    from pydantic import BaseModel, Field

    class Candidate(BaseModel):
        legal_name: str
        primary_business_name: str | None = None
        city: str | None = None
        state: str | None = None
        country: str | None = None
        related_person: bool | None = None
        broker_dealer_sec_number: str | None = None
        legal_entity_identifier: str | None = None
        sma_aum: float | None = Field(default=None, ge=0)
        source_page: int | None = Field(default=None, ge=1)

    class Result(BaseModel):
        custodians: list[Candidate]

    provider = os.getenv("ADV_CUSTODIAN_PROVIDER", "ollama").strip().lower()
    model_name = os.getenv("ADV_CUSTODIAN_MODEL", "qwen3:8b")
    timeout = int(os.getenv("ADV_CUSTODIAN_TIMEOUT_SECONDS", "60"))
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        model: Any = ChatOllama(model=model_name, temperature=0)
    elif provider in {"openai", "freetoken"}:
        from langchain_openai import ChatOpenAI
        options: dict[str, Any] = {"model": model_name, "temperature": 0, "timeout": timeout}
        if provider == "freetoken":
            options.update({"base_url": os.getenv("FREETOKEN_BASE_URL", "http://127.0.0.1:8000/v1"), "api_key": os.getenv("FREETOKEN_API_KEY", "local")})
        model = ChatOpenAI(**options)
    else:
        raise ValueError("ADV_CUSTODIAN_PROVIDER must be ollama, openai, or freetoken")
    schedule = re.search(r"(?:SECTION\s+)?5\.K\.\(3\)", text, re.I)
    bounded = (text[schedule.start():] if schedule else text)[: int(os.getenv("ADV_CUSTODIAN_MAX_CONTENT_CHARS", "50000"))]
    response = model.with_structured_output(Result).invoke(
        "Extract only explicitly reported Schedule D 5.K.(3) custodian rows. "
        "Never infer missing values and use null for ambiguous fields.\n\n" + bounded
    )
    rows = response.custodians if hasattr(response, "custodians") else response["custodians"]
    candidates = [CustodianCandidate(**(row.model_dump() if hasattr(row, "model_dump") else row)) for row in rows]
    return [candidate for candidate in candidates if _grounded(candidate, bounded)]


def _store_pdf_in_r2(payload: bytes, dataset_version: str, firm_id: str, source_hash: str) -> str | None:
    names = ("CLOUDFLARE_R2_ACCOUNT_ID", "CLOUDFLARE_R2_ACCESS_KEY_ID", "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "CLOUDFLARE_R2_BUCKET")
    config = {name: os.getenv(name) for name in names}
    if not all(config.values()):
        return None
    import boto3
    key = f"adv/{dataset_version}/{firm_id}/{source_hash}.pdf"
    client = boto3.client("s3", endpoint_url=f"https://{config['CLOUDFLARE_R2_ACCOUNT_ID']}.r2.cloudflarestorage.com", aws_access_key_id=config["CLOUDFLARE_R2_ACCESS_KEY_ID"], aws_secret_access_key=config["CLOUDFLARE_R2_SECRET_ACCESS_KEY"], region_name="auto")
    client.put_object(Bucket=config["CLOUDFLARE_R2_BUCKET"], Key=key, Body=payload, ContentType="application/pdf", Metadata={"sha256": source_hash, "firm-crd": firm_id, "dataset-version": dataset_version})
    return key


def _claim_job(database_url: str, dataset_version: str | None = None) -> dict[str, Any] | None:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute("""
          update adv_refresh_jobs set status='RUNNING',attempt_count=attempt_count+1,
            started_at=now(),completed_at=null,error_message=null,
            lease_expires_at=now()+(%s*interval '1 second'),updated_at=now()
          where job_id=(select job_id from adv_refresh_jobs
            where (
              (status in ('QUEUED','RETRY_WAIT') and (next_attempt_at is null or next_attempt_at<=now()))
              or (status='RUNNING' and lease_expires_at<=now())
            ) and attempt_count<max_attempts and (%s::text is null or dataset_version=%s::text)
            order by created_at for update skip locked limit 1)
          returning *
        """, (int(os.getenv("ADV_OCR_LEASE_SECONDS", "3600")), dataset_version, dataset_version)).fetchone()
        return dict(row) if row else None


def _download_pdf(url: str, limiter: RequestRateLimiter) -> bytes:
    limiter.wait()
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"}, timeout=(10, 90))
    except (requests.Timeout, requests.ConnectionError) as error:
        raise AdvTransientError(str(error)) from error
    if response.status_code in {404, 410}:
        raise AdvUnavailableError(f"Official ADV PDF returned HTTP {response.status_code}")
    if response.status_code == 429 or response.status_code >= 500:
        raise AdvTransientError(f"Official ADV PDF returned HTTP {response.status_code}")
    response.raise_for_status()
    return response.content


def _finish_error(database_url: str, job: dict[str, Any], error: Exception) -> str:
    import psycopg
    status = "FAILED"
    if isinstance(error, AdvUnavailableError):
        status = "UNAVAILABLE"
    elif isinstance(error, AdvTransientError) and int(job["attempt_count"]) < int(job["max_attempts"]):
        status = "RETRY_WAIT"
    delay = min(900, 15 * (2 ** max(0, int(job["attempt_count"]) - 1)))
    with psycopg.connect(database_url) as conn:
        conn.execute("""update adv_refresh_jobs set status=%s,error_message=%s,
          next_attempt_at=case when %s='RETRY_WAIT' then now()+(%s*interval '1 second') else null end,
          completed_at=case when %s='RETRY_WAIT' then null else now() end,lease_expires_at=null,updated_at=now() where job_id=%s""",
          (status, str(error)[:1000], status, delay, status, job["job_id"]))
        conn.execute("update adv_current_filings set last_error=%s,updated_at=now() where firm_id=%s and dataset_version=%s", (str(error)[:1000], str(job["firm_id"]), job["dataset_version"]))
    return status


def _process_job(database_url: str, job: dict[str, Any], limiter: RequestRateLimiter) -> str:
    import psycopg
    from psycopg.types.json import Jsonb
    firm_id, version = str(job["firm_id"]), job["dataset_version"]
    with psycopg.connect(database_url) as conn:
        filing = conn.execute("""select p.pdf_url,f.sma_custodian_reporting_required
          from adv_current_filings p join adv_firm_facts f using(firm_id,dataset_version)
          where p.firm_id=%s and p.dataset_version=%s""", (firm_id, version)).fetchone()
    if not filing:
        raise RuntimeError("Structured current filing must be published before OCR refresh")
    requirement_status = filing[1]
    payload = _download_pdf(filing[0], limiter)
    validate_pdf(payload, firm_id)
    source_hash = hashlib.sha256(payload).hexdigest()
    text, pages = _ocr_pdf(payload)
    if firm_id not in re.sub(r"\D", "", text):
        raise ValueError("OCR identity validation did not find the expected CRD")
    r2_key, artifact_error = None, None
    try:
        r2_key = _store_pdf_in_r2(payload, version, firm_id, source_hash)
    except Exception as error:
        # Source URL, content hash, page, and extracted values remain sufficient
        # provenance. Artifact storage is retriable and must not discard facts.
        artifact_error = str(error)[:500]
    candidates = parse_custodians(text)
    method, fallback_error = "DETERMINISTIC_OCR", None
    if not candidates:
        try:
            candidates = parse_custodians_with_langchain(text)
            if candidates:
                method = "LANGCHAIN_GROUNDED_FALLBACK"
        except Exception as error:
            fallback_error = str(error)[:500]
    decisions = [_auto_accept(candidate, text, method) for candidate in candidates]
    accepted = [candidate for candidate, decision in zip(candidates, decisions) if decision[0]]
    rejected_reasons = [decision[1] for decision in decisions if not decision[0]]
    status = "COMPLETED" if accepted and len(accepted) == len(candidates) else "FAILED"
    if not candidates:
        status = "NO_CUSTODIAN_ROWS" if requirement_status is not True else "FAILED"
    if status == "FAILED":
        reason = "; ".join(rejected_reasons) if rejected_reasons else "required Schedule 5.K.(3) rows were not extracted"
        raise ValueError(reason)
    summary = {"processing_status": status, "candidate_count": len(candidates), "accepted_count": len(accepted), "rejected_reasons": rejected_reasons, "extraction_method": method, "extraction_version": EXTRACTION_VERSION, "pdf_hash": source_hash, "page_count": pages, "fallback_error": fallback_error, "artifact_error": artifact_error, "acceptance_rule": "SOURCE_GROUNDED_V1"}
    with psycopg.connect(database_url) as conn:
        conn.execute("delete from adv_custodians where firm_id=%s and dataset_version=%s and review_status in ('PROPOSED','ACCEPTED')", (firm_id, version))
        for candidate in accepted:
            conn.execute("""insert into adv_custodians
              (custodian_id,firm_id,dataset_version,legal_name,primary_business_name,city,state,country,related_person,broker_dealer_sec_number,legal_entity_identifier,sma_aum,source_page,source_hash,confidence,review_status,extraction_method,extraction_version,created_at,updated_at)
              values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACCEPTED',%s,%s,now(),now())
              on conflict (custodian_id) do update set primary_business_name=excluded.primary_business_name,
              city=excluded.city,state=excluded.state,country=excluded.country,related_person=excluded.related_person,
              broker_dealer_sec_number=excluded.broker_dealer_sec_number,legal_entity_identifier=excluded.legal_entity_identifier,
              sma_aum=excluded.sma_aum,source_page=excluded.source_page,confidence=excluded.confidence,
              review_status='ACCEPTED',extraction_method=excluded.extraction_method,extraction_version=excluded.extraction_version,updated_at=now()""",
              (stable_custodian_id(firm_id, version, candidate.legal_name, source_hash), firm_id, version, candidate.legal_name,
               candidate.primary_business_name, candidate.city, candidate.state, candidate.country, candidate.related_person,
               candidate.broker_dealer_sec_number, candidate.legal_entity_identifier, candidate.sma_aum, candidate.source_page,
               source_hash, "HIGH" if method == "DETERMINISTIC_OCR" else "MEDIUM", method, EXTRACTION_VERSION))
        conn.execute("""update adv_current_filings set pdf_hash=%s,pdf_r2_key=%s,page_count=%s,
          retrieval_status='PDF_AVAILABLE',identity_status='CRD_OCR_MATCHED',validation_status='PDF_VALIDATED',
          ocr_version=%s,last_successful_at=now(),last_error=null,updated_at=now()
          where firm_id=%s and dataset_version=%s""", (source_hash, r2_key, pages, OCR_VERSION, firm_id, version))
        conn.execute("update adv_refresh_jobs set status=%s,result_summary=%s,next_attempt_at=null,lease_expires_at=null,completed_at=now(),updated_at=now() where job_id=%s", (status, Jsonb(summary), job["job_id"]))
    return status


def process_queue(database_url: str, limit: int = 10, workers: int = 2, requests_per_second: float = 2.0, dataset_version: str | None = None) -> dict[str, int]:
    if limit < 1 or workers < 1 or workers > 8:
        raise ValueError("limit must be positive and workers must be between 1 and 8")
    preflight()
    limiter = RequestRateLimiter(requests_per_second)
    counts = {"completed": 0, "no_custodian_rows": 0, "retry_wait": 0, "unavailable": 0, "failed": 0}

    def run_one() -> str | None:
        job = _claim_job(database_url, dataset_version)
        if not job:
            return None
        try:
            return _process_job(database_url, job, limiter)
        except Exception as error:
            return _finish_error(database_url, job, error)

    remaining = limit
    while remaining:
        batch_size = min(workers, remaining)
        with ThreadPoolExecutor(max_workers=batch_size) as pool:
            results = [future.result() for future in as_completed([pool.submit(run_one) for _ in range(batch_size)])]
        claimed = [result for result in results if result is not None]
        if not claimed:
            break
        remaining -= len(claimed)
        for result in claimed:
            key = str(result).lower()
            if key in counts:
                counts[key] += 1
    return {**counts, "processed": limit - remaining}


def process_until_idle(database_url: str, batch_size: int = 25, workers: int = 2, requests_per_second: float = 2.0, dataset_version: str | None = None) -> dict[str, int]:
    """Drain currently claimable work in bounded batches; delayed retries remain resumable."""
    total = {"completed": 0, "no_custodian_rows": 0, "retry_wait": 0, "unavailable": 0, "failed": 0, "processed": 0}
    while True:
        result = process_queue(database_url, batch_size, workers, requests_per_second, dataset_version)
        for key in total:
            total[key] += int(result.get(key, 0))
        if result["processed"] == 0:
            return total


def queue_refresh(database_url: str, firm_id: str, dataset_version: str | None = None) -> dict[str, str]:
    import psycopg
    with psycopg.connect(database_url) as conn:
        version_row = (dataset_version,) if dataset_version else conn.execute("select dataset_version from firms where firm_id=%s order by dataset_version desc limit 1", (firm_id,)).fetchone()
        if not version_row:
            raise ValueError(f"Dashboard firm not found: {firm_id}")
        version = version_row[0]
        existing = conn.execute("select job_id,status,dataset_version from adv_refresh_jobs where firm_id=%s and dataset_version=%s and status=any(%s) order by created_at desc limit 1", (firm_id, version, list(ACTIVE_JOB_STATUSES))).fetchone()
        if existing:
            return {"job_id": existing[0], "status": existing[1], "dataset_version": existing[2]}
        job_id = str(uuid.uuid4())
        conn.execute("insert into adv_refresh_jobs (job_id,firm_id,dataset_version,status,requested_by,max_attempts,created_at,updated_at) values (%s,%s,%s,'QUEUED','LOCAL_CLI',3,now(),now())", (job_id, firm_id, version))
        return {"job_id": job_id, "status": "QUEUED", "dataset_version": version}


def queue_dataset(database_url: str, dataset_version: str | None = None, force: bool = False) -> dict[str, Any]:
    import psycopg
    with psycopg.connect(database_url) as conn:
        version_row = (dataset_version,) if dataset_version else conn.execute("select dataset_version from dataset_versions order by published_at desc limit 1").fetchone()
        if not version_row:
            raise ValueError("No published dataset is available")
        version = version_row[0]
        queued = conn.execute("""with inserted as (
          insert into adv_refresh_jobs (job_id,firm_id,dataset_version,status,scope,requested_by,max_attempts,created_at,updated_at)
          select md5(f.firm_id || ':' || f.dataset_version || ':' || clock_timestamp()::text || ':' || random()::text),
            f.firm_id,f.dataset_version,'QUEUED','SCHEDULE_5K3','DATASET_BATCH',3,now(),now()
          from adv_firm_facts f
          where f.dataset_version=%s and f.sma_custodian_reporting_required is not false
          and not exists (select 1 from adv_refresh_jobs j where j.firm_id=f.firm_id and j.dataset_version=f.dataset_version
            and (j.status in ('QUEUED','RUNNING','RETRY_WAIT') or (%s=false and j.status in ('COMPLETED','NO_CUSTODIAN_ROWS'))))
          returning job_id
        ) select count(*) from inserted""", (version, force)).fetchone()[0]
        applicable = conn.execute("select count(*) from adv_firm_facts where dataset_version=%s and sma_custodian_reporting_required is true", (version,)).fetchone()[0]
        unknown = conn.execute("select count(*) from adv_firm_facts where dataset_version=%s and sma_custodian_reporting_required is null", (version,)).fetchone()[0]
        not_required = conn.execute("select count(*) from adv_firm_facts where dataset_version=%s and sma_custodian_reporting_required is false", (version,)).fetchone()[0]
    return {"dataset_version": version, "queued": queued, "applicable": applicable, "requirement_unknown": unknown, "not_required": not_required}


def coverage_status(database_url: str, dataset_version: str | None = None) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        version_row = (dataset_version,) if dataset_version else conn.execute("select dataset_version from dataset_versions order by published_at desc limit 1").fetchone()
        if not version_row:
            raise ValueError("No published dataset is available")
        version = version_row[0]
        statuses = conn.execute("""with latest as (
          select distinct on (firm_id) firm_id,status from adv_refresh_jobs
          where dataset_version=%s order by firm_id,created_at desc
        ) select status,count(*)::int count from latest group by status order by status""", (version,)).fetchall()
        facts = conn.execute("""select count(*)::int total,
          count(*) filter (where sma_custodian_reporting_required is true)::int applicable,
          count(*) filter (where sma_custodian_reporting_required is false)::int not_required,
          count(*) filter (where sma_custodian_reporting_required is null)::int requirement_unavailable
          from adv_firm_facts where dataset_version=%s""", (version,)).fetchone()
        custodians = conn.execute("select count(*)::int count,count(distinct firm_id)::int firms from adv_custodians where dataset_version=%s", (version,)).fetchone()
    return {"dataset_version": version, **dict(facts), "job_statuses": {row["status"]: row["count"] for row in statuses}, "custodian_rows": custodians["count"], "firms_with_custodians": custodians["firms"]}


def recover_expired_jobs(database_url: str, dataset_version: str | None = None, include_legacy_unleased: bool = False) -> dict[str, int]:
    """Recover expired leases; legacy unleased jobs require explicit opt-in."""
    import psycopg
    with psycopg.connect(database_url) as conn:
        clause, params = ("and dataset_version=%s", (dataset_version,)) if dataset_version else ("", ())
        legacy = "or (lease_expires_at is null and started_at is not null)" if include_legacy_unleased else ""
        result = conn.execute(f"""update adv_refresh_jobs set status='RETRY_WAIT',next_attempt_at=now(),
          lease_expires_at=null,error_message=coalesce(error_message,'Worker lease expired; safely requeued'),updated_at=now()
          where status='RUNNING' and (lease_expires_at<=now() {legacy}) {clause}""", params)
    return {"requeued": result.rowcount}


def requeue_stopped_job(database_url: str, job_id: str) -> dict[str, int]:
    """Explicitly requeue one confirmed-stopped local worker job."""
    import psycopg
    with psycopg.connect(database_url) as conn:
        result = conn.execute("""update adv_refresh_jobs set status='RETRY_WAIT',next_attempt_at=now(),
          lease_expires_at=null,error_message=coalesce(error_message,'Stopped local worker; safely requeued'),updated_at=now()
          where job_id=%s and status='RUNNING'""", (job_id,))
    return {"requeued": result.rowcount}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("queue", "queue-dataset", "process-queue", "process-until-idle", "recover-expired", "requeue-stopped", "status"))
    parser.add_argument("--database-url", default=os.getenv("PUBLISHER_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--dataset-version")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--requests-per-second", type=float, default=2.0)
    parser.add_argument("--firm-id")
    parser.add_argument("--job-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--include-legacy-unleased", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if args.command == "queue":
        if not args.firm_id:
            parser.error("--firm-id is required for queue")
        result = queue_refresh(args.database_url, args.firm_id, args.dataset_version)
    elif args.command == "queue-dataset":
        result = queue_dataset(args.database_url, args.dataset_version, args.force)
    elif args.command == "status":
        result = coverage_status(args.database_url, args.dataset_version)
    elif args.command == "recover-expired":
        result = recover_expired_jobs(args.database_url, args.dataset_version, args.include_legacy_unleased)
    elif args.command == "requeue-stopped":
        if not args.job_id:
            parser.error("--job-id is required for requeue-stopped")
        result = requeue_stopped_job(args.database_url, args.job_id)
    elif args.command == "process-until-idle":
        result = process_until_idle(args.database_url, args.limit, args.workers, args.requests_per_second, args.dataset_version)
    else:
        result = process_queue(args.database_url, args.limit, args.workers, args.requests_per_second, args.dataset_version)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
