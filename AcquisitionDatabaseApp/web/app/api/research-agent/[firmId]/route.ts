import { auth } from "../../../../auth";
import { queueResearchAgentJob } from "../../../../lib/research-agent";

export async function POST(_: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const { firmId } = await params;
    const job = await queueResearchAgentJob(firmId, session.user.email || session.user.id);
    return Response.json(job, { status: 202 });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to queue research job";
    const status = message === "Firm not found" ? 404 : 400;
    return Response.json({ error: message }, { status });
  }
}
