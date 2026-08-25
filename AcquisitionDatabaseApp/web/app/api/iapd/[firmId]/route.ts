import { auth } from "../../../../auth";
import { db } from "../../../../lib/db";
import { getIapdFirmBundle } from "../../../../lib/iapd-bundles";
import { sql } from "drizzle-orm";

export async function GET(request: Request, { params }: { params: Promise<{ firmId: string }> }) {
  if (!(await auth())) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const { firmId } = await params;
  const firm = await db.execute(sql`select dataset_version from firms where firm_id=${firmId} order by dataset_version desc limit 1`);
  if (!firm.rows[0]) return Response.json({ error: "Firm not found" }, { status: 404 });
  const result = await getIapdFirmBundle(String((firm.rows[0] as any).dataset_version), firmId);
  if (result.status === "AVAILABLE" && result.bundle) {
    const url = new URL(request.url);
    const requestedLimit = Number.parseInt(url.searchParams.get("limit") || "200", 10);
    const requestedOffset = Number.parseInt(url.searchParams.get("offset") || "0", 10);
    const limit = Number.isFinite(requestedLimit) ? Math.min(500, Math.max(1, requestedLimit)) : 200;
    const offset = Number.isFinite(requestedOffset) ? Math.max(0, requestedOffset) : 0;
    const representatives = Array.isArray(result.bundle.representatives) ? result.bundle.representatives : [];
    return Response.json({
      ...result,
      bundle: { ...result.bundle, representatives: representatives.slice(offset, offset + limit) },
      pagination: { offset, limit, total: representatives.length, has_more: offset + limit < representatives.length },
    });
  }
  return Response.json(result, { status: result.status === "NO_CURRENT_REPRESENTATIVE" ? 200 : 503 });
}
