CREATE TABLE "iapd_firm_summary_batch_counts" (
	"snapshot_id" text NOT NULL,
	"member_name" text NOT NULL,
	"firm_id" text NOT NULL,
	"representative_count" integer NOT NULL,
	"active_representative_count" integer NOT NULL,
	"representative_with_disclosure_count" integer NOT NULL,
	"representative_with_other_business_count" integer NOT NULL,
	"registration_count" integer NOT NULL,
	"registration_status_counts" jsonb NOT NULL,
	"processed_at" timestamp with time zone NOT NULL,
	CONSTRAINT "iapd_firm_summary_batch_counts_pk" PRIMARY KEY("snapshot_id","member_name","firm_id")
);
--> statement-breakpoint
CREATE INDEX "iapd_firm_summary_batch_counts_snapshot_idx" ON "iapd_firm_summary_batch_counts" USING btree ("snapshot_id","firm_id");
--> statement-breakpoint
CREATE TABLE "iapd_firm_principals" (
	"principal_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"filing_date" text,
	"schedule_type" text NOT NULL,
	"principal_type" text NOT NULL,
	"full_legal_name" text NOT NULL,
	"title_status" text,
	"date_acquired" text,
	"ownership_code" text,
	"control_person" boolean,
	"public_reporting_company" boolean,
	"related_crd" text,
	"source_url" text,
	"source_file_name" text NOT NULL,
	"content_hash" text NOT NULL,
	"published_at" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE INDEX "iapd_firm_principals_firm_idx" ON "iapd_firm_principals" USING btree ("firm_id","filing_date");
--> statement-breakpoint
CREATE TABLE "iapd_firm_coverage" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"snapshot_id" text,
	"coverage_status" text NOT NULL,
	"representative_count" integer,
	"individual_principal_count" integer NOT NULL DEFAULT 0,
	"entity_principal_count" integer NOT NULL DEFAULT 0,
	"reported_state_iar_count" integer,
	"details" jsonb NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "iapd_firm_coverage_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE INDEX "iapd_firm_coverage_status_idx" ON "iapd_firm_coverage" USING btree ("dataset_version","coverage_status");
