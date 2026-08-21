CREATE TABLE "iapd_import_issues" (
	"issue_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text,
	"individual_crd" text,
	"stage" text NOT NULL,
	"severity" text NOT NULL,
	"issue_code" text NOT NULL,
	"message" text NOT NULL,
	"details" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_live_enrichments" (
	"enrichment_id" text PRIMARY KEY NOT NULL,
	"capture_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"full_name" text,
	"current_employer_name" text,
	"current_employer_crd" text,
	"business_address" text,
	"phone" text,
	"website" text,
	"registration_status" text,
	"registration_date" text,
	"branch_locations" jsonb,
	"disclosure_summary" text,
	"normalized_fields" jsonb NOT NULL,
	"confidence" text NOT NULL,
	"freshness" text NOT NULL,
	"retrieved_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_reconciliations" (
	"reconciliation_id" text PRIMARY KEY NOT NULL,
	"individual_crd" text NOT NULL,
	"snapshot_id" text,
	"capture_id" text,
	"effective_fields" jsonb NOT NULL,
	"freshness" text NOT NULL,
	"confidence" text NOT NULL,
	"conflicts" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_live_captures" (
	"capture_id" text PRIMARY KEY NOT NULL,
	"individual_crd" text NOT NULL,
	"source_url" text NOT NULL,
	"source_title" text,
	"retrieved_at" timestamp with time zone NOT NULL,
	"retrieval_status" text NOT NULL,
	"content_hash" text NOT NULL,
	"parser_version" text NOT NULL,
	"raw_payload" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_import_issue_idx" ON "iapd_import_issues" USING btree ("snapshot_id","issue_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_live_enrichment_crd_idx" ON "iapd_individual_live_enrichments" USING btree ("individual_crd","enrichment_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_reconciliation_crd_idx" ON "iapd_individual_reconciliations" USING btree ("individual_crd","reconciliation_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_live_capture_crd_idx" ON "iapd_live_captures" USING btree ("individual_crd","capture_id");