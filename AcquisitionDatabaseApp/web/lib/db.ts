import "server-only";

import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import { attachDatabasePool } from "@vercel/functions";
import * as schema from "./schema";
import { validateVercelDeployment } from "./deployment-policy";

validateVercelDeployment(process.env);
const globalForDb = globalThis as unknown as { pool?: Pool };
export const pool = globalForDb.pool ?? new Pool({ connectionString: process.env.DATABASE_URL });
if (process.env.VERCEL) attachDatabasePool(pool);
if (process.env.NODE_ENV !== "production") globalForDb.pool = pool;
export const db = drizzle(pool, { schema });
