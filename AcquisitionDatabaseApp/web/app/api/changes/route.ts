import { auth } from "../../../auth"; import { db } from "../../../lib/db"; import { sql } from "drizzle-orm";
export async function GET(){if(!(await auth()))return Response.json({error:"Unauthorized"},{status:401});const r=await db.execute(sql`select * from change_intelligence order by created_at desc limit 200`);return Response.json(r.rows);}
