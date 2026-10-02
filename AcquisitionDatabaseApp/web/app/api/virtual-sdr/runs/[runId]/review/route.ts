import { auth } from "../../../../../../auth";
import { reviewVirtualSdrRun } from "../../../../../../lib/virtual-sdr";

export async function PATCH(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const body = await request.json().catch(() => ({}));
  try {
    const result = await reviewVirtualSdrRun({
      runId: (await params).runId,
      decision: String(body.decision || ""),
      reviewer: session.user.email || session.user.id || "authenticated-user",
      notes: typeof body.notes === "string" ? body.notes : undefined,
      edits: body.edits && typeof body.edits === "object" ? body.edits : undefined,
    });
    return Response.json(result, { status: 202 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to review SDR brief" }, { status: 400 });
  }
}
