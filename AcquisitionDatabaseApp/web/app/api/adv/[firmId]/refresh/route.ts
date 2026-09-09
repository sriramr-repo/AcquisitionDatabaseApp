import { auth } from "../../../../../auth";
import { pool } from "../../../../../lib/db";
import crypto from "node:crypto";

export async function POST(_: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const { firmId } = await params;
  const found = await pool.query("select dataset_version from firms where firm_id=$1 order by dataset_version desc limit 1", [firmId]);
  if (!found.rows[0]) return Response.json({ error: "Firm not found" }, { status: 404 });
  const existing = await pool.query("select * from adv_refresh_jobs where firm_id=$1 and dataset_version=$2 and status in ('QUEUED','RUNNING') order by created_at desc limit 1", [firmId, found.rows[0].dataset_version]);
  if (existing.rows[0]) return Response.json(existing.rows[0]);
  const jobId = crypto.randomUUID();
  const result = await pool.query("insert into adv_refresh_jobs (job_id,firm_id,dataset_version,status,requested_by,created_at,updated_at) values ($1,$2,$3,'QUEUED',$4,now(),now()) returning *", [jobId, firmId, found.rows[0].dataset_version, session.user.email || session.user.id]);
  return Response.json(result.rows[0], { status: 202 });
}
