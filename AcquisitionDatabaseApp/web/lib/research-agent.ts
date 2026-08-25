import crypto from "node:crypto";
import { sql } from "drizzle-orm";
import { db } from "./db";

export const promptVersion = "scm-research-prompt-v7";
export const extractionVersion = "scm-research-extraction-v7";
const priorityABatchMaximum = 25;

function boundedInt(value: string | undefined, fallback: number, min: number, max: number) {
  const parsed = value ? Number.parseInt(value, 10) : fallback;
  if (!Number.isFinite(parsed) || parsed < min || parsed > max) return fallback;
  return parsed;
}

export async function queueResearchAgentJob(firmId: string, requestedBy: string) {
  const firm = await db.execute(sql`select dataset_version from firms where firm_id=${firmId} order by dataset_version desc limit 1`);
  const datasetVersion = String(firm.rows[0]?.dataset_version || "");
  if (!datasetVersion) throw new Error("Firm not found");

  const maxPages = boundedInt(process.env.RESEARCH_AGENT_MAX_PAGES, 6, 1, 20);
  const maxTokens = boundedInt(process.env.RESEARCH_AGENT_MAX_TOKENS, 700, 256, 16000);
  const timeoutSeconds = boundedInt(process.env.RESEARCH_AGENT_TIMEOUT_SECONDS, 60, 5, 300);
  const maxContentChars = boundedInt(process.env.RESEARCH_AGENT_MAX_CONTENT_CHARS, 120000, 5000, 500000);
  const maxChunkChars = boundedInt(process.env.RESEARCH_AGENT_MAX_CHUNK_CHARS, 6000, 500, 20000);
  const maxChunks = boundedInt(process.env.RESEARCH_AGENT_MAX_CHUNKS, 8, 1, 100);
  const maxChunksPerRequest = boundedInt(process.env.RESEARCH_AGENT_MAX_CHUNKS_PER_REQUEST, 1, 1, 8);
  const maxAttempts = boundedInt(process.env.RESEARCH_AGENT_MAX_ATTEMPTS, 3, 1, 10);
  const captures = await db.execute(sql`select * from (
    select c.capture_id,c.source_id,coalesce(c.content_hash,s.content_hash,'') as content_hash,c.created_at
      from research_evidence_captures c join research_sources s on s.source_id=c.source_id
      where s.firm_id=${firmId} and s.dataset_version=${datasetVersion} and c.content is not null and c.content<>''
    union all
    select * from (
      select distinct on (lc.capture_id) lc.capture_id,'iapd-live:'||lc.capture_id as source_id,lc.content_hash,lc.retrieved_at as created_at
        from iapd_live_captures lc join iapd_individual_current_employments e on e.individual_crd=lc.individual_crd
        where e.employer_firm_crd=${firmId} and lc.retrieval_status='SUCCESS' and lc.raw_payload is not null
        order by lc.capture_id,lc.retrieved_at desc
    ) iapd
    ) evidence order by created_at desc limit ${maxPages}`);
  if (!captures.rows.length) throw new Error("No captured evidence is available for this firm");
  const normalized = captures.rows.map((row:any)=>[String(row.capture_id),String(row.source_id),String(row.content_hash)]).sort((a,b)=>a[0].localeCompare(b[0]));
  const sourceSetHash = crypto.createHash("sha256").update(JSON.stringify(normalized)).digest("hex");
  const captureIds = captures.rows.map((row:any)=>String(row.capture_id));
  for (const row of captures.rows.filter((item:any)=>String(item.source_id).startsWith("iapd-live:"))) {
    await db.execute(sql`insert into research_sources
      (source_id,firm_id,dataset_version,source_type,source_url,source_title,source_authority,accessed_at,retrieval_status,content_hash,field_supported,source_notes,created_at,updated_at)
      select ${String(row.source_id)},${firmId},${datasetVersion},'iapd_live',lc.source_url,lc.source_title,'SEC/IAPD',lc.retrieved_at,'REVIEW_REQUIRED',lc.content_hash,'candidate_research_observations','Materialized from an existing IAPD live capture',now(),now()
      from iapd_live_captures lc where lc.capture_id=${String(row.capture_id)} on conflict (source_id) do nothing`);
  }
  const jobId = crypto.randomUUID();
  const provider = process.env.RESEARCH_AGENT_PROVIDER || "ollama";
  const model = process.env.RESEARCH_AGENT_MODEL || (provider === "ollama" ? "qwen3:8b" : provider === "freetoken" ? "Qwen3-30B-A3B" : "gpt-4.1-mini");
  const result = await db.execute(sql`insert into research_agent_jobs
    (job_id,firm_id,dataset_version,status,source_capture_ids,source_set_hash,prompt_version,extraction_version,model_provider,model_name,max_pages,max_tokens,timeout_seconds,max_content_chars,max_chunk_chars,max_chunks,max_chunks_per_request,max_attempts,requested_by)
    values (${jobId},${firmId},${datasetVersion},'QUEUED',${JSON.stringify(captureIds)}::jsonb,${sourceSetHash},${promptVersion},${extractionVersion},${provider},${model},${maxPages},${maxTokens},${timeoutSeconds},${maxContentChars},${maxChunkChars},${maxChunks},${maxChunksPerRequest},${maxAttempts},${requestedBy})
    on conflict (firm_id,dataset_version,source_set_hash,extraction_version) do update set
      status=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE') then 'QUEUED' else research_agent_jobs.status end,
      error_message=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE') then null else research_agent_jobs.error_message end,
      started_at=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE') then null else research_agent_jobs.started_at end,
      completed_at=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE') then null else research_agent_jobs.completed_at end,
      model_provider=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.model_provider else research_agent_jobs.model_provider end,
      model_name=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.model_name else research_agent_jobs.model_name end,
      max_pages=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.max_pages else research_agent_jobs.max_pages end,
      max_tokens=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.max_tokens else research_agent_jobs.max_tokens end,
      timeout_seconds=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.timeout_seconds else research_agent_jobs.timeout_seconds end,
      max_content_chars=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.max_content_chars else research_agent_jobs.max_content_chars end,
      max_chunk_chars=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.max_chunk_chars else research_agent_jobs.max_chunk_chars end,
      max_chunks=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.max_chunks else research_agent_jobs.max_chunks end,
      max_chunks_per_request=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.max_chunks_per_request else research_agent_jobs.max_chunks_per_request end,
      max_attempts=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE','QUEUED') then excluded.max_attempts else research_agent_jobs.max_attempts end,
      attempt_count=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE') then 0 else research_agent_jobs.attempt_count end,
      next_attempt_at=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE') then null else research_agent_jobs.next_attempt_at end,
      last_error_category=case when research_agent_jobs.status in ('FAILED','UNAVAILABLE') then null else research_agent_jobs.last_error_category end,
      requested_by=coalesce(excluded.requested_by,research_agent_jobs.requested_by),
      updated_at=now()
    returning *`);
  return result.rows[0];
}

function boundedBatchSize(value: number) {
  if (!Number.isInteger(value) || value < 1 || value > priorityABatchMaximum) {
    throw new Error(`Batch size must be between 1 and ${priorityABatchMaximum}`);
  }
  return value;
}

export async function researchAgentProgress() {
  const result = await db.execute(sql`with latest_dataset as (
      select dataset_version from dataset_versions order by published_at desc limit 1
    ), priority_firms as (
      select f.firm_id,f.dataset_version
      from firms f join firm_scores s using(firm_id,dataset_version) join latest_dataset d using(dataset_version)
      where s.priority_category='PRIORITY_A'
    ), coverage as (
      select p.*,(exists(
        select 1 from research_sources s join research_evidence_captures c using(source_id)
        where s.firm_id=p.firm_id and s.dataset_version=p.dataset_version
          and c.content is not null and c.content<>''
      ) or exists(
        select 1 from iapd_individual_current_employments e join iapd_live_captures lc on lc.individual_crd=e.individual_crd
        where e.employer_firm_crd=p.firm_id and lc.retrieval_status='SUCCESS' and lc.raw_payload is not null
      )) as has_evidence
      from priority_firms p
    ), latest_jobs as (
      select distinct on (j.firm_id,j.dataset_version) j.firm_id,j.dataset_version,j.status,j.attempt_count,j.max_attempts,j.updated_at
      from research_agent_jobs j join latest_dataset d using(dataset_version)
      where j.prompt_version=${promptVersion} and j.extraction_version=${extractionVersion}
      order by j.firm_id,j.dataset_version,j.created_at desc
    ), observation_counts as (
      select o.firm_id,o.dataset_version,count(*) filter(where o.review_status='PROPOSED')::int as proposed,
        count(*) filter(where o.review_status='CONFLICTING')::int as conflicting
      from research_observations o join latest_dataset d using(dataset_version)
      group by o.firm_id,o.dataset_version
    ) select count(*)::int as total_firms,
      count(*) filter(where c.has_evidence)::int as firms_with_evidence,
      count(*) filter(where not c.has_evidence)::int as firms_without_evidence,
      count(*) filter(where c.has_evidence and (j.status is null or j.status in ('FAILED','UNAVAILABLE')))::int as queueable,
      count(*) filter(where j.status='QUEUED')::int as queued,
      count(*) filter(where j.status='RUNNING')::int as running,
      count(*) filter(where j.status='REVIEW_REQUIRED')::int as review_required,
      count(*) filter(where j.status='COMPLETED')::int as completed,
      count(*) filter(where j.status='FAILED')::int as failed,
      count(*) filter(where j.status='UNAVAILABLE')::int as unavailable,
      coalesce(sum(o.proposed),0)::int as proposed_observations,
      coalesce(sum(o.conflicting),0)::int as conflicting_observations
      from coverage c left join latest_jobs j using(firm_id,dataset_version)
      left join observation_counts o using(firm_id,dataset_version)`);
  return result.rows[0] || {};
}

export async function queuePriorityAResearchBatch(requestedBy: string, requestedLimit = 10) {
  const limit = boundedBatchSize(requestedLimit);
  const before = await researchAgentProgress();
  const candidates = await db.execute(sql`with latest_dataset as (
      select dataset_version from dataset_versions order by published_at desc limit 1
    ), latest_jobs as (
      select distinct on (j.firm_id,j.dataset_version) j.firm_id,j.dataset_version,j.status
      from research_agent_jobs j join latest_dataset d using(dataset_version)
      where j.prompt_version=${promptVersion} and j.extraction_version=${extractionVersion}
      order by j.firm_id,j.dataset_version,j.created_at desc
    ) select f.firm_id,s.acquisition_score
      from firms f join firm_scores s using(firm_id,dataset_version) join latest_dataset d using(dataset_version)
      left join latest_jobs j using(firm_id,dataset_version)
      where s.priority_category='PRIORITY_A'
        and (j.status is null or j.status in ('FAILED','UNAVAILABLE'))
        and (exists(
          select 1 from research_sources rs join research_evidence_captures c using(source_id)
          where rs.firm_id=f.firm_id and rs.dataset_version=f.dataset_version
            and c.content is not null and c.content<>''
        ) or exists(
          select 1 from iapd_individual_current_employments e join iapd_live_captures lc on lc.individual_crd=e.individual_crd
          where e.employer_firm_crd=f.firm_id and lc.retrieval_status='SUCCESS' and lc.raw_payload is not null
        ))
      order by s.acquisition_score desc nulls last,f.firm_id
      limit ${limit}`);
  const jobs: any[] = [];
  const failures: Array<{firmId:string; error:string}> = [];
  const rows = candidates.rows as Array<{firm_id:string}>;
  for (let index = 0; index < rows.length; index += 5) {
    const slice = rows.slice(index, index + 5);
    const settled = await Promise.allSettled(
      slice.map(row => queueResearchAgentJob(String(row.firm_id), requestedBy))
    );
    settled.forEach((outcome, offset) => {
      const firmId = String(slice[offset].firm_id);
      if (outcome.status === "fulfilled") jobs.push(outcome.value);
      else failures.push({firmId, error: outcome.reason instanceof Error ? outcome.reason.message : "Queue failed"});
    });
  }
  return {
    priority: "PRIORITY_A",
    requestedLimit: limit,
    selected: rows.length,
    queued: jobs.length,
    failed: failures.length,
    failures,
    jobIds: jobs.map((job:any) => String(job.job_id)),
    remainingQueueable: Math.max(0, Number(before.queueable || 0) - jobs.length),
    progress: await researchAgentProgress(),
  };
}
