ALTER TABLE "adv_refresh_jobs" ADD COLUMN IF NOT EXISTS "lease_expires_at" timestamp with time zone;
CREATE INDEX IF NOT EXISTS "adv_refresh_jobs_lease_idx"
  ON "adv_refresh_jobs" USING btree ("status", "lease_expires_at");
