import { auth } from "../../../../../auth";
import { db } from "../../../../../lib/db";
import { sql } from "drizzle-orm";

export async function GET(_: Request, { params }: { params: Promise<{ jobId: string }> }) {
  if (!(await auth())) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const { jobId } = await params;
  const result = await db.execute(sql`select * from enrichment_jobs where job_id=${jobId} limit 1`);
  if (!result.rows[0]) return Response.json({ error: "Enrichment job not found" }, { status: 404 });
  return Response.json(result.rows[0]);
}
