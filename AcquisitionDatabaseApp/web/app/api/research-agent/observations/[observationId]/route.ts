import { auth } from "../../../../../auth";
import { db } from "../../../../../lib/db";
import { sql } from "drizzle-orm";
import { extractionVersion, promptVersion } from "../../../../../lib/research-agent";

const allowed = new Set(["ACCEPTED", "REJECTED", "CONFLICTING"]);

export async function PATCH(req: Request, { params }: { params: Promise<{ observationId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const status = String(body.status || "").toUpperCase();
  if (!allowed.has(status)) return Response.json({ error: "Invalid review status" }, { status: 400 });
  const { observationId } = await params;
  const result = await db.execute(sql`update research_observations o set review_status=${status},reviewer=${session.user.email || session.user.id},reviewed_at=now(),review_notes=${body.notes || null},updated_at=now()
    where o.observation_id=${observationId}
      and exists (select 1 from research_sources s where s.source_id=o.source_id)
      and (o.agent_job_id is null or exists (
        select 1 from research_agent_jobs j where j.job_id=o.agent_job_id
          and j.prompt_version=${promptVersion} and j.extraction_version=${extractionVersion}
      )) returning o.*`);
  if (!result.rows[0]) return Response.json({ error: "Observation or provenance source not found" }, { status: 404 });
  return Response.json(result.rows[0]);
}
