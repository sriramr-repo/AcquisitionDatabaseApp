import { auth } from "../../../../auth";
import {
  queuePriorityAResearchBatch,
  researchAgentProgress,
} from "../../../../lib/research-agent";

export async function GET() {
  if (!(await auth())) return Response.json({ error: "Unauthorized" }, { status: 401 });
  return Response.json(await researchAgentProgress());
}

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const body = await request.json().catch(() => ({}));
  if (body.priority && body.priority !== "PRIORITY_A") {
    return Response.json(
      { error: "The controlled rollout currently supports Priority A only" },
      { status: 400 },
    );
  }
  try {
    const limit = body.limit == null ? 10 : Number(body.limit);
    const result = await queuePriorityAResearchBatch(
      session.user.email || session.user.id,
      limit,
    );
    return Response.json(result, { status: 202 });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Unable to queue research batch" },
      { status: 400 },
    );
  }
}
