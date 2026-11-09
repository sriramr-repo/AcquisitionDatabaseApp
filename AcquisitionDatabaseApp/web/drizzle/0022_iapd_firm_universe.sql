ALTER TABLE "dataset_versions" ADD COLUMN IF NOT EXISTS "source_firm_count" integer;
ALTER TABLE "dataset_versions" ADD COLUMN IF NOT EXISTS "registered_firm_count" integer;
ALTER TABLE "dataset_versions" ADD COLUMN IF NOT EXISTS "era_only_firm_count" integer;
ALTER TABLE "dataset_versions" ADD COLUMN IF NOT EXISTS "dual_registered_firm_count" integer;
ALTER TABLE "dataset_versions" ADD COLUMN IF NOT EXISTS "acquisition_target_count" integer;

ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "canonical_population_source" text;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "population_classification" text;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "is_registered" boolean;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "is_sec_registered" boolean;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "is_state_registered" boolean;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "is_era_only" boolean;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "has_era_relationship" boolean;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "is_dual_registered" boolean;
ALTER TABLE "firms" ADD COLUMN IF NOT EXISTS "registration_review_required" boolean;

CREATE INDEX IF NOT EXISTS "firms_registration_scope_idx"
  ON "firms" ("dataset_version", "is_registered", "is_sec_registered", "is_state_registered");
