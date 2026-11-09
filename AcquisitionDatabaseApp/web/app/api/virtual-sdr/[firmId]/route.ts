import { auth } from "../../../../auth";
import { startVirtualSdrRun, virtualSdrData } from "../../../../lib/virtual-sdr";
import { outreachEligibilityResponse, requireOutreachEligible } from "../../../../lib/outreach-eligibility";

export async function GET(_: Request, { params }: { params: Promise<{ firmId: string }> }) {
  if (!(await auth())) return Response.json({ error: "Unauthorized" }, { status: 401 });
  return Response.json(await virtualSdrData((await params).firmId));
}

export async function POST(_: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const firmId = (await params).firmId;
    await requireOutreachEligible(firmId);
    const run = await startVirtualSdrRun(firmId, session.user.email || session.user.id || "authenticated-user");
    return Response.json(run, { status: run.status === "UNAVAILABLE" ? 503 : 202 });
  } catch (error) {
    const response = outreachEligibilityResponse(error);
    if (response) return response;
    return Response.json({ error: error instanceof Error ? error.message : "Unable to prepare SDR brief" }, { status: 400 });
  }
}
