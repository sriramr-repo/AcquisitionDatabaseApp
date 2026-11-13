import { auth } from "../../../../auth";
import { db } from "../../../../lib/db";
import { outreachEligibilityResponse, requireOutreachEligible } from "../../../../lib/outreach-eligibility";
import { analystIdentity, parseShortlistAddRequest, shortlistRequestMatchesActiveDataset } from "../../../../lib/analyst-shortlist";
import { sql } from "drizzle-orm";

export async function PUT(request: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  const analystId = analystIdentity(session);
  if (!analystId) return Response.json({ error: "Please sign in to update your Outreach shortlist." }, { status: 401 });

  const { firmId } = await params;
  const body = await request.json().catch(() => null);
  const addRequest = parseShortlistAddRequest(body);
  if (!addRequest) {
    return Response.json({ error: "datasetVersion is required" }, { status: 400 });
  }

  try {
    const eligible = await requireOutreachEligible(firmId);
    if (!shortlistRequestMatchesActiveDataset(addRequest, eligible.dataset_version)) {
      return Response.json({ error: "The active dataset changed. Refresh Target Explorer and try again." }, { status: 409 });
    }
  } catch (error) {
    const response = outreachEligibilityResponse(error);
    if (response) return response;
    throw error;
  }

  await db.execute(sql`insert into analyst_outreach_shortlists (analyst_id, firm_id, added_at)
    values (${analystId}, ${firmId}, now()) on conflict (analyst_id, firm_id) do nothing`);
  return Response.json({ firmId, isShortlisted: true });
}

export async function DELETE(_: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  const analystId = analystIdentity(session);
  if (!analystId) return Response.json({ error: "Please sign in to update your Outreach shortlist." }, { status: 401 });
  const { firmId } = await params;
  await db.execute(sql`delete from analyst_outreach_shortlists where analyst_id = ${analystId} and firm_id = ${firmId}`);
  return Response.json({ firmId, isShortlisted: false });
}
