import { auth } from "../../../../auth";
import { startVirtualSdrRun, virtualSdrData } from "../../../../lib/virtual-sdr";

export async function GET(_: Request, { params }: { params: Promise<{ firmId: string }> }) {
  if (!(await auth())) return Response.json({ error: "Unauthorized" }, { status: 401 });
  return Response.json(await virtualSdrData((await params).firmId));
}

export async function POST(_: Request, { params }: { params: Promise<{ firmId: string }> }) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const run = await startVirtualSdrRun((await params).firmId, session.user.email || session.user.id || "authenticated-user");
    return Response.json(run, { status: run.status === "UNAVAILABLE" ? 503 : 202 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to prepare SDR brief" }, { status: 400 });
  }
}
