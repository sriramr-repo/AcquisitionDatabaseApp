import { auth } from "../../../../auth";
import { db } from "../../../../lib/db";
import { sql } from "drizzle-orm";
import { sanitizeTargetColumnPreferences } from "../../../../lib/target-column-preferences";

const preferenceKey = "target-explorer-columns-v1";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const result = await db.execute(sql`select preference_value from analyst_preferences where analyst_id = ${session.user.id} and preference_key = ${preferenceKey}`);
  return Response.json((result.rows[0] as { preference_value?: unknown } | undefined)?.preference_value ?? null);
}

export async function PUT(request: Request) {
  const session = await auth();
  if (!session?.user?.id) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const body = await request.json().catch(() => null);
  const preferences = sanitizeTargetColumnPreferences(body);
  if (!preferences) return Response.json({ error: "Invalid column preferences" }, { status: 400 });
  await db.execute(sql`insert into analyst_preferences (analyst_id, preference_key, preference_value, updated_at)
    values (${session.user.id}, ${preferenceKey}, ${JSON.stringify(preferences)}::jsonb, now())
    on conflict (analyst_id, preference_key) do update set preference_value = excluded.preference_value, updated_at = now()`);
  return Response.json(preferences);
}
