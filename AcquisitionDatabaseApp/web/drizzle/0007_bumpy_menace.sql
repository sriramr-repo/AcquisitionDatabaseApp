CREATE TABLE "iapd_firm_summaries" (
	"snapshot_id" text NOT NULL,
	"snapshot_date" text NOT NULL,
	"firm_id" text NOT NULL,
	"source_url" text NOT NULL,
	"content_hash" text NOT NULL,
	"representative_count" integer NOT NULL,
	"active_representative_count" integer NOT NULL,
	"representative_with_disclosure_count" integer NOT NULL,
	"representative_with_other_business_count" integer NOT NULL,
	"registration_count" integer NOT NULL,
	"registration_status_counts" jsonb NOT NULL,
	"published_at" timestamp with time zone NOT NULL,
	CONSTRAINT "iapd_firm_summaries_snapshot_id_firm_id_pk" PRIMARY KEY("snapshot_id","firm_id")
);
--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_firm_summary_firm_snapshot_idx" ON "iapd_firm_summaries" USING btree ("firm_id","snapshot_id");