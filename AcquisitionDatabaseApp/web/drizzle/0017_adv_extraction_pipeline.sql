ALTER TABLE "adv_refresh_jobs" ADD COLUMN IF NOT EXISTS "max_attempts" integer DEFAULT 3 NOT NULL;
ALTER TABLE "adv_refresh_jobs" ADD COLUMN IF NOT EXISTS "next_attempt_at" timestamp with time zone;
ALTER TABLE "adv_refresh_jobs" ADD COLUMN IF NOT EXISTS "result_summary" jsonb;
ALTER TABLE "adv_custodians" ADD COLUMN IF NOT EXISTS "extraction_method" text DEFAULT 'DETERMINISTIC_OCR' NOT NULL;
ALTER TABLE "adv_custodians" ADD COLUMN IF NOT EXISTS "extraction_version" text DEFAULT 'scm-adv-custodian-v1' NOT NULL;

CREATE INDEX IF NOT EXISTS "adv_refresh_jobs_claim_idx"
  ON "adv_refresh_jobs" USING btree ("status", "next_attempt_at", "created_at");

CREATE TABLE IF NOT EXISTS "adv_schedule_observations" (
  "observation_id" text PRIMARY KEY NOT NULL,
  "firm_id" text NOT NULL,
  "dataset_version" text NOT NULL,
  "field_key" text NOT NULL,
  "form_item" text NOT NULL,
  "value_json" jsonb NOT NULL,
  "source_url" text NOT NULL,
  "source_page" integer,
  "source_excerpt" text,
  "source_hash" text NOT NULL,
  "extraction_method" text NOT NULL,
  "extraction_version" text NOT NULL,
  "confidence" text NOT NULL,
  "review_status" text DEFAULT 'PROPOSED' NOT NULL,
  "reviewer" text,
  "reviewed_at" timestamp with time zone,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS "adv_schedule_observation_version_idx"
  ON "adv_schedule_observations" USING btree
  ("firm_id", "dataset_version", "field_key", "source_hash", "extraction_version");
CREATE INDEX IF NOT EXISTS "adv_schedule_observation_review_idx"
  ON "adv_schedule_observations" USING btree ("dataset_version", "review_status", "field_key");
