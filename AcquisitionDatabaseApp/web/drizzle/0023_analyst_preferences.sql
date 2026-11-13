CREATE TABLE "adv_client_categories" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"category_code" text NOT NULL,
	"category_label" text NOT NULL,
	"client_count" integer,
	"fewer_than_five" boolean,
	"aum" real,
	"other_description" text,
	"source_fields" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adv_client_categories_firm_id_dataset_version_category_code_pk" PRIMARY KEY("firm_id","dataset_version","category_code")
);
--> statement-breakpoint
CREATE TABLE "adv_current_filings" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"filing_date" text,
	"legal_name" text,
	"sec_number" text,
	"iapd_search_url" text NOT NULL,
	"iapd_summary_url" text NOT NULL,
	"pdf_url" text NOT NULL,
	"pdf_hash" text,
	"pdf_r2_key" text,
	"page_count" integer,
	"retrieval_status" text NOT NULL,
	"identity_status" text NOT NULL,
	"validation_status" text NOT NULL,
	"parser_version" text NOT NULL,
	"ocr_version" text,
	"last_successful_at" timestamp with time zone,
	"last_error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adv_current_filings_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "adv_custodians" (
	"custodian_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"legal_name" text,
	"primary_business_name" text,
	"city" text,
	"state" text,
	"country" text,
	"related_person" boolean,
	"broker_dealer_sec_number" text,
	"legal_entity_identifier" text,
	"sma_aum" real,
	"source_page" integer,
	"source_hash" text NOT NULL,
	"confidence" text NOT NULL,
	"review_status" text DEFAULT 'PROPOSED' NOT NULL,
	"extraction_method" text DEFAULT 'DETERMINISTIC_OCR' NOT NULL,
	"extraction_version" text DEFAULT 'scm-adv-custodian-v1' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "adv_firm_facts" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"item_1o_over_1b" boolean,
	"item_1o_asset_band" text,
	"sec_registration_basis" jsonb NOT NULL,
	"succession_indicator" boolean,
	"succession_date" text,
	"employee_count" integer,
	"advisory_employee_count" integer,
	"broker_dealer_rep_count" integer,
	"state_iar_count" integer,
	"other_adviser_iar_count" integer,
	"insurance_agent_count" integer,
	"solicitor_count" integer,
	"compensation_arrangements" jsonb NOT NULL,
	"provides_continuous_management" boolean,
	"discretionary_aum" real,
	"non_discretionary_aum" real,
	"total_aum" real,
	"discretionary_account_count" integer,
	"non_discretionary_account_count" integer,
	"total_account_count" integer,
	"non_us_client_aum" real,
	"advisory_activities" jsonb NOT NULL,
	"client_categories" jsonb NOT NULL,
	"sma_custodian_reporting_required" boolean,
	"source_fields" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adv_firm_facts_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "adv_refresh_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"status" text DEFAULT 'QUEUED' NOT NULL,
	"scope" text DEFAULT 'CURRENT_FILING' NOT NULL,
	"requested_by" text,
	"attempt_count" integer DEFAULT 0 NOT NULL,
	"max_attempts" integer DEFAULT 3 NOT NULL,
	"next_attempt_at" timestamp with time zone,
	"lease_expires_at" timestamp with time zone,
	"result_summary" jsonb,
	"error_message" text,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "adv_schedule_observations" (
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
--> statement-breakpoint
CREATE TABLE "analyst_preferences" (
	"analyst_id" text NOT NULL,
	"preference_key" text NOT NULL,
	"preference_value" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "analyst_preferences_analyst_id_preference_key_pk" PRIMARY KEY("analyst_id","preference_key")
);
--> statement-breakpoint
CREATE TABLE "fact_definitions" (
	"field_key" text PRIMARY KEY NOT NULL,
	"display_label" text NOT NULL,
	"short_definition" text NOT NULL,
	"category" text NOT NULL,
	"form_item" text,
	"data_class" text NOT NULL,
	"value_type" text NOT NULL,
	"primary_source_type" text NOT NULL,
	"primary_source_field" text,
	"fallback_source_type" text,
	"extraction_method" text NOT NULL,
	"null_meaning" text NOT NULL,
	"editable" boolean DEFAULT false NOT NULL,
	"requires_evidence" boolean DEFAULT false NOT NULL,
	"used_in_scoring" boolean DEFAULT false NOT NULL,
	"dashboard_section" text NOT NULL,
	"display_order" integer DEFAULT 0 NOT NULL,
	"definition_version" text NOT NULL,
	"active" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_feed_runs" (
	"run_id" text PRIMARY KEY NOT NULL,
	"requested_date" text NOT NULL,
	"selected_date" text,
	"status" text NOT NULL,
	"source_url" text,
	"source_hash" text,
	"attempts" jsonb NOT NULL,
	"result_counts" jsonb NOT NULL,
	"started_at" timestamp with time zone NOT NULL,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_firm_change_summaries" (
	"comparison_id" text NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"new_representative_count" integer DEFAULT 0 NOT NULL,
	"representative_no_longer_present_count" integer DEFAULT 0 NOT NULL,
	"employer_change_count" integer DEFAULT 0 NOT NULL,
	"registration_change_count" integer DEFAULT 0 NOT NULL,
	"disclosure_change_count" integer DEFAULT 0 NOT NULL,
	"material_contact_change_count" integer DEFAULT 0 NOT NULL,
	"representative_samples" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "iapd_firm_change_summaries_comparison_id_firm_id_pk" PRIMARY KEY("comparison_id","firm_id")
);
--> statement-breakpoint
CREATE TABLE "iapd_live_batches" (
	"batch_id" text PRIMARY KEY NOT NULL,
	"status" text NOT NULL,
	"scope" text NOT NULL,
	"options" jsonb NOT NULL,
	"counts" jsonb NOT NULL,
	"checkpoint_crd" text,
	"started_at" timestamp with time zone NOT NULL,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_live_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"batch_id" text,
	"individual_crd" text NOT NULL,
	"source_url" text NOT NULL,
	"parser_version" text NOT NULL,
	"priority_order" integer NOT NULL,
	"status" text DEFAULT 'QUEUED' NOT NULL,
	"attempt_count" integer DEFAULT 0 NOT NULL,
	"max_attempts" integer DEFAULT 3 NOT NULL,
	"last_attempt_at" timestamp with time zone,
	"next_attempt_at" timestamp with time zone,
	"last_success_at" timestamp with time zone,
	"last_content_hash" text,
	"failure_reason" text,
	"result_summary" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_manual_review_queue" (
	"review_id" text PRIMARY KEY NOT NULL,
	"individual_crd" text NOT NULL,
	"reason_code" text NOT NULL,
	"status" text DEFAULT 'OPEN' NOT NULL,
	"monthly_snapshot_id" text,
	"live_capture_id" text,
	"details" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_snapshot_comparisons" (
	"comparison_id" text PRIMARY KEY NOT NULL,
	"dataset_version" text NOT NULL,
	"current_snapshot_id" text NOT NULL,
	"previous_snapshot_id" text,
	"current_snapshot_date" text NOT NULL,
	"previous_snapshot_date" text,
	"status" text NOT NULL,
	"counts" jsonb NOT NULL,
	"national_affected_firm_count" integer DEFAULT 0 NOT NULL,
	"published_firm_count" integer DEFAULT 0 NOT NULL,
	"artifact_name" text NOT NULL,
	"interpretation_guardrails" jsonb NOT NULL,
	"published_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "seller_intent_current" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"status" text DEFAULT 'UNKNOWN' NOT NULL,
	"confidence" text,
	"primary_evidence_id" text,
	"confirmed_by" text,
	"confirmed_at" timestamp with time zone,
	"last_reviewed_at" timestamp with time zone,
	"notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "seller_intent_current_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "seller_intent_evidence" (
	"evidence_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"source_type" text NOT NULL,
	"source_record_id" text,
	"source_url" text,
	"evidence_date" timestamp with time zone NOT NULL,
	"evidence_excerpt" text NOT NULL,
	"claim_polarity" text NOT NULL,
	"source_authority" text NOT NULL,
	"confidence" text NOT NULL,
	"proposed_status" text NOT NULL,
	"review_status" text DEFAULT 'PROPOSED' NOT NULL,
	"reviewer" text,
	"reviewed_at" timestamp with time zone,
	"review_notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "seller_intent_history" (
	"history_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"from_status" text,
	"to_status" text NOT NULL,
	"evidence_id" text,
	"changed_by" text NOT NULL,
	"change_reason" text,
	"changed_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "dataset_versions" ADD COLUMN "source_firm_count" integer;--> statement-breakpoint
ALTER TABLE "dataset_versions" ADD COLUMN "registered_firm_count" integer;--> statement-breakpoint
ALTER TABLE "dataset_versions" ADD COLUMN "era_only_firm_count" integer;--> statement-breakpoint
ALTER TABLE "dataset_versions" ADD COLUMN "dual_registered_firm_count" integer;--> statement-breakpoint
ALTER TABLE "dataset_versions" ADD COLUMN "acquisition_target_count" integer;--> statement-breakpoint
ALTER TABLE "firm_facts" ADD COLUMN "main_office_postal_code" text;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "canonical_population_source" text;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "population_classification" text;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "is_registered" boolean;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "is_sec_registered" boolean;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "is_state_registered" boolean;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "is_era_only" boolean;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "has_era_relationship" boolean;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "is_dual_registered" boolean;--> statement-breakpoint
ALTER TABLE "firms" ADD COLUMN "registration_review_required" boolean;--> statement-breakpoint
CREATE UNIQUE INDEX "adv_schedule_observation_version_idx" ON "adv_schedule_observations" USING btree ("firm_id","dataset_version","field_key","source_hash","extraction_version");--> statement-breakpoint
CREATE INDEX "iapd_firm_change_summaries_dataset_idx" ON "iapd_firm_change_summaries" USING btree ("dataset_version","firm_id");--> statement-breakpoint
CREATE INDEX "iapd_firm_change_summaries_comparison_idx" ON "iapd_firm_change_summaries" USING btree ("comparison_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_live_job_version_idx" ON "iapd_live_jobs" USING btree ("individual_crd","parser_version");--> statement-breakpoint
CREATE INDEX "firms_registration_scope_idx" ON "firms" USING btree ("dataset_version","is_registered","is_sec_registered","is_state_registered");