CREATE TABLE IF NOT EXISTS "iapd_snapshot_comparisons" (
	"comparison_id" text PRIMARY KEY NOT NULL,
	"dataset_version" text NOT NULL,
	"current_snapshot_id" text NOT NULL,
	"previous_snapshot_id" text,
	"current_snapshot_date" text NOT NULL,
	"previous_snapshot_date" text,
	"status" text NOT NULL,
	"counts" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"national_affected_firm_count" integer DEFAULT 0 NOT NULL,
	"published_firm_count" integer DEFAULT 0 NOT NULL,
	"artifact_name" text NOT NULL,
	"interpretation_guardrails" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"published_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "iapd_snapshot_comparisons_latest_idx" ON "iapd_snapshot_comparisons" ("dataset_version","current_snapshot_date" DESC,"published_at" DESC);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "iapd_firm_change_summaries" (
	"comparison_id" text NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"new_representative_count" integer DEFAULT 0 NOT NULL,
	"representative_no_longer_present_count" integer DEFAULT 0 NOT NULL,
	"employer_change_count" integer DEFAULT 0 NOT NULL,
	"registration_change_count" integer DEFAULT 0 NOT NULL,
	"disclosure_change_count" integer DEFAULT 0 NOT NULL,
	"material_contact_change_count" integer DEFAULT 0 NOT NULL,
	"representative_samples" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "iapd_firm_change_summaries_pk" PRIMARY KEY("comparison_id","firm_id")
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "iapd_firm_change_summaries_dataset_idx" ON "iapd_firm_change_summaries" ("dataset_version","firm_id");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "iapd_firm_change_summaries_comparison_idx" ON "iapd_firm_change_summaries" ("comparison_id");
