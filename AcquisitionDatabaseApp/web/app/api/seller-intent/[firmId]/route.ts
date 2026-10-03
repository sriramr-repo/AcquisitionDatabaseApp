import { auth } from "../../../../auth";
import { pool } from "../../../../lib/db";
import { sellerIntentSourceTypes, sellerIntentStatuses } from "../../../../lib/seller-intent";
import crypto from "node:crypto";

export async function POST(req: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const { firmId } = await params;
  const body = await req.json().catch(() => ({}));
  const proposedStatus = String(body.proposedStatus || "").toUpperCase();
  const sourceType = String(body.sourceType || "").toUpperCase();
  const excerpt = String(body.evidenceExcerpt || "").trim();
  if (!sellerIntentStatuses.includes(proposedStatus) || proposedStatus === "UNKNOWN" || proposedStatus === "STALE") return Response.json({ error: "Invalid proposed status" }, { status: 400 });
  if (!sellerIntentSourceTypes.includes(sourceType)) return Response.json({ error: "Seller intent requires a permitted evidence source" }, { status: 400 });
  if (proposedStatus === "NOT_INTERESTED" && !["OWNER_COMMUNICATION","AUTHORIZED_REPRESENTATIVE","OUTREACH_RESPONSE","CALL","MEETING"].includes(sourceType)) return Response.json({ error: "NOT_INTERESTED requires direct or authorized evidence" }, { status: 400 });
  if (proposedStatus === "FORMAL_PROCESS" && !["OWNER_COMMUNICATION","AUTHORIZED_REPRESENTATIVE","AUTHORIZED_INTERMEDIARY","PUBLIC_FORMAL_PROCESS"].includes(sourceType)) return Response.json({ error: "FORMAL_PROCESS requires direct, intermediary, or public process evidence" }, { status: 400 });
  if (excerpt.length < 10) return Response.json({ error: "A specific evidence excerpt is required" }, { status: 400 });
  const versionResult = await pool.query("select dataset_version from firms where firm_id=$1 order by dataset_version desc limit 1", [firmId]);
  const datasetVersion = versionResult.rows[0]?.dataset_version;
  if (!datasetVersion) return Response.json({ error: "Firm not found" }, { status: 404 });
  const evidenceId = crypto.randomUUID();
  const result = await pool.query(`insert into seller_intent_evidence
    (evidence_id,firm_id,dataset_version,source_type,source_record_id,source_url,evidence_date,evidence_excerpt,claim_polarity,source_authority,confidence,proposed_status,review_status,created_at,updated_at)
    values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'PROPOSED',now(),now()) returning *`,
    [evidenceId, firmId, datasetVersion, sourceType, body.sourceRecordId || null, body.sourceUrl || null, body.evidenceDate || new Date(), excerpt, body.claimPolarity || "SUPPORTS", body.sourceAuthority || "DIRECT_OR_AUTHORIZED", body.confidence || "MEDIUM", proposedStatus]);
  return Response.json(result.rows[0], { status: 201 });
}

export async function PATCH(req: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const reviewer = session.user.email || session.user.id;
  const { firmId } = await params;
  const body = await req.json().catch(() => ({}));
  const decision = String(body.decision || "").toUpperCase();
  const client = await pool.connect();
  try {
    await client.query("begin");
    const evidence = body.evidenceId ? (await client.query("select * from seller_intent_evidence where evidence_id=$1 and firm_id=$2 for update", [body.evidenceId, firmId])).rows[0] : null;
    if (decision === "ACCEPT") {
      if (!evidence || evidence.review_status !== "PROPOSED") throw new Error("A proposed evidence record is required");
      const current = (await client.query("select * from seller_intent_current where firm_id=$1 and dataset_version=$2 for update", [firmId, evidence.dataset_version])).rows[0];
      let next = evidence.proposed_status;
      if (current?.status && !["UNKNOWN", "STALE", next].includes(current.status)) next = "CONFLICTING";
      await client.query("update seller_intent_evidence set review_status='ACCEPTED',reviewer=$1,reviewed_at=now(),review_notes=$2,updated_at=now() where evidence_id=$3", [reviewer, body.notes || null, evidence.evidence_id]);
      await client.query(`insert into seller_intent_current (firm_id,dataset_version,status,confidence,primary_evidence_id,confirmed_by,confirmed_at,last_reviewed_at,created_at,updated_at)
        values ($1,$2,$3,$4,$5,$6,now(),now(),now(),now()) on conflict (firm_id,dataset_version) do update set status=excluded.status,confidence=excluded.confidence,primary_evidence_id=excluded.primary_evidence_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,last_reviewed_at=excluded.last_reviewed_at,updated_at=now()`, [firmId, evidence.dataset_version, next, evidence.confidence, evidence.evidence_id, reviewer]);
      await client.query("insert into seller_intent_history (history_id,firm_id,dataset_version,from_status,to_status,evidence_id,changed_by,change_reason) values ($1,$2,$3,$4,$5,$6,$7,$8)", [crypto.randomUUID(), firmId, evidence.dataset_version, current?.status || "UNKNOWN", next, evidence.evidence_id, reviewer, body.notes || "Evidence accepted"]);
    } else if (decision === "REJECT") {
      if (!evidence) throw new Error("Evidence record not found");
      await client.query("update seller_intent_evidence set review_status='REJECTED',reviewer=$1,reviewed_at=now(),review_notes=$2,updated_at=now() where evidence_id=$3", [reviewer, body.notes || null, evidence.evidence_id]);
    } else if (decision === "MARK_STALE") {
      const current = (await client.query("select * from seller_intent_current where firm_id=$1 order by dataset_version desc limit 1 for update", [firmId])).rows[0];
      if (!current) throw new Error("No seller-intent status exists to mark stale");
      await client.query("update seller_intent_current set status='STALE',confirmed_by=$1,confirmed_at=now(),last_reviewed_at=now(),notes=$2,updated_at=now() where firm_id=$3 and dataset_version=$4", [reviewer, body.notes || null, firmId, current.dataset_version]);
      await client.query("insert into seller_intent_history (history_id,firm_id,dataset_version,from_status,to_status,evidence_id,changed_by,change_reason) values ($1,$2,$3,$4,'STALE',$5,$6,$7)", [crypto.randomUUID(), firmId, current.dataset_version, current.status, current.primary_evidence_id, reviewer, body.notes || "Manually marked stale"]);
    } else throw new Error("Invalid decision");
    await client.query("commit");
    return Response.json({ ok: true });
  } catch (error) {
    await client.query("rollback");
    return Response.json({ error: error instanceof Error ? error.message : "Unable to update seller intent" }, { status: 400 });
  } finally { client.release(); }
}
