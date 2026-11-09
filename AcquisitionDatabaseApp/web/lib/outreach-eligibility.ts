import { sql } from "drizzle-orm";
import { db } from "./db";
import { ERA_OUTREACH_BLOCKED, outreachAllowed } from "./outreach-policy";

export class OutreachEligibilityError extends Error {
  constructor(message: string, readonly status: 404 | 409) {
    super(message);
    this.name = "OutreachEligibilityError";
  }
}

export async function requireOutreachEligible(firmId: string, datasetVersion?: string) {
  const result = datasetVersion
    ? await db.execute(sql`select dataset_version,is_registered,is_era_only from firms
        where firm_id=${firmId} and dataset_version=${datasetVersion} limit 1`)
    : await db.execute(sql`select f.dataset_version,f.is_registered,f.is_era_only from firms f
        where f.firm_id=${firmId} and f.dataset_version=(
          select dataset_version from dataset_versions
          order by published_at desc nulls last,dataset_version desc limit 1
        ) limit 1`);
  const firm = result.rows[0] as { dataset_version: string; is_registered: boolean | null; is_era_only: boolean | null } | undefined;
  if (!firm) throw new OutreachEligibilityError("Firm not found in the selected dataset", 404);
  if (!outreachAllowed(firm)) throw new OutreachEligibilityError(ERA_OUTREACH_BLOCKED, 409);
  return firm;
}

export function outreachEligibilityResponse(error: unknown): Response | null {
  return error instanceof OutreachEligibilityError
    ? Response.json({ error: error.message }, { status: error.status })
    : null;
}
