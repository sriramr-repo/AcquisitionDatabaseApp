import { auth } from "../../../../../../auth";
import { db } from "../../../../../../lib/db";
import { sql } from "drizzle-orm";

export async function GET(_: Request, { params }: { params: Promise<{ artifactId: string }> }) {
  if (!(await auth())) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const artifactId = (await params).artifactId;
  const result = await db.execute(sql`select a.content,r.firm_id,r.dataset_version,a.version from virtual_sdr_artifacts a join virtual_sdr_runs r using(run_id) where a.artifact_id=${artifactId} limit 1`);
  const artifact: any = result.rows[0];
  if (!artifact) return Response.json({ error: "Artifact not found" }, { status: 404 });
  const body = JSON.stringify(typeof artifact.content === "string" ? JSON.parse(artifact.content) : artifact.content, null, 2);
  return new Response(body, { headers: {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Disposition": `attachment; filename="ceo-brief-${artifact.firm_id}-v${artifact.version}.json"`,
    "Cache-Control": "private, no-store",
  }});
}
