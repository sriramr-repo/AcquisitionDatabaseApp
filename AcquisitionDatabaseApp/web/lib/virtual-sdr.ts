import crypto from "node:crypto";
import { sql } from "drizzle-orm";
import { db } from "./db";

export const sdrWorkflowVersion = "scm-virtual-sdr-v1";
export const sdrPromptVersion = "scm-virtual-sdr-prompt-v1";
const allowedDecisions = new Set(["APPROVED", "REJECTED", "REVISION_REQUESTED"]);

function deploymentConfig() {
  const url = process.env.LANGGRAPH_DEPLOYMENT_URL?.replace(/\/$/, "");
  const apiKey = process.env.LANGSMITH_API_KEY;
  const assistantId = process.env.LANGGRAPH_ASSISTANT_ID || "virtual_sdr";
  if (!url || !apiKey) throw new Error("LangSmith Deployment is not configured");
  return { url, apiKey, assistantId };
}

async function deploymentRequest(path: string, body: unknown) {
  const config = deploymentConfig();
  const response = await fetch(`${config.url}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Api-Key": config.apiKey,
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof payload?.detail === "string" ? payload.detail : `LangSmith Deployment returned HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

export async function sdrInputSnapshot(firmId: string) {
  const firm = await db.execute(sql`select firm_id,dataset_version,updated_at from firms where firm_id=${firmId} order by dataset_version desc limit 1`);
  const row: any = firm.rows[0];
  if (!row) throw new Error("Firm not found");
  const datasetVersion = String(row.dataset_version);
  const [facts, scores, observations, principals, contacts] = await Promise.all([
    db.execute(sql`select updated_at from firm_facts where firm_id=${firmId} and dataset_version=${datasetVersion}`),
    db.execute(sql`select updated_at from firm_scores where firm_id=${firmId} and dataset_version=${datasetVersion}`),
    db.execute(sql`select observation_id,source_id,updated_at from research_observations where firm_id=${firmId} and dataset_version=${datasetVersion} and review_status='ACCEPTED' order by observation_id`),
    db.execute(sql`select principal_id,content_hash from iapd_firm_principals where firm_id=${firmId} order by principal_id`),
    db.execute(sql`select contact_id,updated_at from contacts where firm_id=${firmId} and dataset_version=${datasetVersion} and verification_status='VERIFIED' order by contact_id`),
  ]);
  const digestInput = {
    firm: row.updated_at,
    facts: facts.rows,
    scores: scores.rows,
    observations: observations.rows,
    principals: principals.rows,
    contacts: contacts.rows,
  };
  const inputHash = crypto.createHash("sha256").update(JSON.stringify(digestInput)).digest("hex");
  return { datasetVersion, inputHash };
}

export async function startVirtualSdrRun(firmId: string, requestedBy: string) {
  const { datasetVersion, inputHash } = await sdrInputSnapshot(firmId);
  const provider = process.env.VIRTUAL_SDR_PROVIDER || "openai";
  const model = process.env.VIRTUAL_SDR_MODEL || (provider === "ollama" ? "qwen3:8b" : provider === "freetoken" ? "Qwen3-30B-A3B" : "gpt-4.1-mini");
  const runId = crypto.randomUUID();
  const inserted = await db.execute(sql`insert into virtual_sdr_runs
    (run_id,firm_id,dataset_version,status,input_hash,workflow_version,prompt_version,model_provider,model_name,requested_by,created_at,updated_at)
    values (${runId},${firmId},${datasetVersion},'REQUESTED',${inputHash},${sdrWorkflowVersion},${sdrPromptVersion},${provider},${model},${requestedBy},now(),now())
    on conflict (firm_id,dataset_version,input_hash,workflow_version) do update set updated_at=virtual_sdr_runs.updated_at
    returning *`);
  const run: any = inserted.rows[0];
  if (run.langgraph_thread_id && !["UNAVAILABLE", "FAILED"].includes(String(run.status))) {
    return { ...run, duplicate: true };
  }
  try {
    const config = deploymentConfig();
    const thread = await deploymentRequest("/threads", {
      metadata: { firm_id: firmId, dataset_version: datasetVersion, workflow_version: sdrWorkflowVersion },
    });
    const threadId = String(thread.thread_id);
    const remoteRun = await deploymentRequest(`/threads/${encodeURIComponent(threadId)}/runs`, {
      assistant_id: config.assistantId,
      input: { run_id: String(run.run_id), firm_id: firmId, dataset_version: datasetVersion, input_hash: inputHash, requested_by: requestedBy },
      metadata: { local_run_id: String(run.run_id), firm_id: firmId, dataset_version: datasetVersion },
    });
    const remoteRunId = String(remoteRun.run_id || "");
    const updated = await db.execute(sql`update virtual_sdr_runs set status=case when status='REQUESTED' then 'QUEUED' else status end,langgraph_thread_id=${threadId},langgraph_run_id=${remoteRunId || null},error_message=case when status='REQUESTED' then null else error_message end,updated_at=now() where run_id=${String(run.run_id)} returning *`);
    return { ...updated.rows[0], duplicate: String(run.run_id) !== runId };
  } catch (error) {
    const message = error instanceof Error ? error.message.slice(0, 1000) : "LangSmith Deployment is unavailable";
    const unavailable = await db.execute(sql`update virtual_sdr_runs set status='UNAVAILABLE',error_message=${message},updated_at=now() where run_id=${String(run.run_id)} returning *`);
    return { ...unavailable.rows[0], duplicate: String(run.run_id) !== runId };
  }
}

export async function virtualSdrData(firmId: string) {
  const runs = await db.execute(sql`select * from virtual_sdr_runs where firm_id=${firmId} order by created_at desc limit 20`);
  const runIds = runs.rows.map((item: any) => String(item.run_id));
  if (!runIds.length) return { runs: [], artifacts: [], reviews: [], qualityChecks: [] };
  const runIdList = sql.join(runIds.map((runId) => sql`${runId}`), sql`, `);
  const [artifacts, reviews, qualityChecks] = await Promise.all([
    db.execute(sql`select * from virtual_sdr_artifacts where run_id in (${runIdList}) order by created_at desc`),
    db.execute(sql`select * from virtual_sdr_reviews where run_id in (${runIdList}) order by created_at desc`),
    db.execute(sql`select * from virtual_sdr_quality_checks where run_id in (${runIdList}) order by created_at desc`),
  ]);
  return { runs: runs.rows, artifacts: artifacts.rows, reviews: reviews.rows, qualityChecks: qualityChecks.rows };
}

export async function reviewVirtualSdrRun(args: { runId: string; decision: string; reviewer: string; notes?: string; edits?: { emailSubject?: string; emailBody?: string; callOpener?: string } }) {
  const decision = args.decision.toUpperCase();
  if (!allowedDecisions.has(decision)) throw new Error("Invalid SDR review decision");
  const selected = await db.execute(sql`select r.*,a.artifact_id,a.content from virtual_sdr_runs r join virtual_sdr_artifacts a on a.artifact_id=r.latest_artifact_id where r.run_id=${args.runId} and r.status='AWAITING_APPROVAL' limit 1`);
  const run: any = selected.rows[0];
  if (!run) throw new Error("SDR run is not awaiting approval");
  const original = typeof run.content === "string" ? JSON.parse(run.content) : run.content;
  const edits = args.edits || {};
  const editedBrief = Object.keys(edits).length ? {
    ...original,
    email_subject: edits.emailSubject ?? original.email_subject,
    email_body: edits.emailBody ?? original.email_body,
    call_opener: edits.callOpener ?? original.call_opener,
  } : null;
  for (const [field, value, maximum] of [
    ["emailSubject", edits.emailSubject, 200],
    ["emailBody", edits.emailBody, 6000],
    ["callOpener", edits.callOpener, 2000],
  ] as const) {
    if (value !== undefined && (typeof value !== "string" || !value.trim() || value.length > maximum)) {
      throw new Error(`${field} is invalid`);
    }
  }
  const reviewId = crypto.randomUUID();
  await db.execute(sql`insert into virtual_sdr_reviews
    (review_id,run_id,artifact_id,decision,reviewer,notes,edited_content,resume_status,created_at,updated_at)
    values (${reviewId},${args.runId},${String(run.artifact_id)},${decision},${args.reviewer},${args.notes || null},${editedBrief ? JSON.stringify(editedBrief) : null}::jsonb,'PENDING',now(),now())`);
  try {
    const config = deploymentConfig();
    const remoteRun = await deploymentRequest(`/threads/${encodeURIComponent(String(run.langgraph_thread_id))}/runs`, {
      assistant_id: config.assistantId,
      command: { resume: { decision, notes: args.notes || null, edited_brief: editedBrief, review_id: reviewId, reviewer: args.reviewer } },
      metadata: { local_run_id: args.runId, review_id: reviewId },
    });
    const resumeRunId = String(remoteRun.run_id || "");
    await db.execute(sql`update virtual_sdr_reviews set resume_status=case when resume_status='PENDING' then 'SUBMITTED' else resume_status end,langgraph_resume_run_id=${resumeRunId || null},updated_at=now() where review_id=${reviewId}`);
    await db.execute(sql`update virtual_sdr_runs set status=case when status='AWAITING_APPROVAL' then 'RESUME_REQUESTED' else status end,langgraph_run_id=${resumeRunId || null},updated_at=now() where run_id=${args.runId}`);
    return { reviewId, status: "SUBMITTED", runId: args.runId };
  } catch (error) {
    const message = error instanceof Error ? error.message.slice(0, 1000) : "Unable to resume SDR run";
    await db.execute(sql`update virtual_sdr_reviews set resume_status='FAILED',error_message=${message},updated_at=now() where review_id=${reviewId}`);
    throw new Error(message);
  }
}
