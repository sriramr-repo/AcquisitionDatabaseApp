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
CREATE INDEX "fact_definitions_section_idx" ON "fact_definitions" USING btree ("dashboard_section","display_order");
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
	CONSTRAINT "adv_current_filings_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE INDEX "adv_current_filings_status_idx" ON "adv_current_filings" USING btree ("dataset_version","retrieval_status");
--> statement-breakpoint
CREATE TABLE "adv_firm_facts" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"item_1o_over_1b" boolean,
	"item_1o_asset_band" text,
	"sec_registration_basis" jsonb NOT NULL DEFAULT '[]'::jsonb,
	"succession_indicator" boolean,
	"succession_date" text,
	"employee_count" integer,
	"advisory_employee_count" integer,
	"broker_dealer_rep_count" integer,
	"state_iar_count" integer,
	"other_adviser_iar_count" integer,
	"insurance_agent_count" integer,
	"solicitor_count" integer,
	"compensation_arrangements" jsonb NOT NULL DEFAULT '[]'::jsonb,
	"provides_continuous_management" boolean,
	"discretionary_aum" numeric,
	"non_discretionary_aum" numeric,
	"total_aum" numeric,
	"discretionary_account_count" integer,
	"non_discretionary_account_count" integer,
	"total_account_count" integer,
	"non_us_client_aum" numeric,
	"advisory_activities" jsonb NOT NULL DEFAULT '[]'::jsonb,
	"client_categories" jsonb NOT NULL DEFAULT '[]'::jsonb,
	"sma_custodian_reporting_required" boolean,
	"source_fields" jsonb NOT NULL DEFAULT '{}'::jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adv_firm_facts_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "adv_client_categories" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"category_code" text NOT NULL,
	"category_label" text NOT NULL,
	"client_count" integer,
	"fewer_than_five" boolean,
	"aum" numeric,
	"other_description" text,
	"source_fields" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "adv_client_categories_pk" PRIMARY KEY("firm_id","dataset_version","category_code")
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
	"sma_aum" numeric,
	"source_page" integer,
	"source_hash" text NOT NULL,
	"confidence" text NOT NULL,
	"review_status" text DEFAULT 'PROPOSED' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE INDEX "adv_custodians_firm_idx" ON "adv_custodians" USING btree ("firm_id","dataset_version");
--> statement-breakpoint
CREATE TABLE "adv_refresh_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"status" text DEFAULT 'QUEUED' NOT NULL,
	"scope" text DEFAULT 'CURRENT_FILING' NOT NULL,
	"requested_by" text,
	"attempt_count" integer DEFAULT 0 NOT NULL,
	"error_message" text,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE INDEX "adv_refresh_jobs_firm_idx" ON "adv_refresh_jobs" USING btree ("firm_id","dataset_version","created_at");
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
CREATE INDEX "seller_intent_evidence_firm_idx" ON "seller_intent_evidence" USING btree ("firm_id","dataset_version","evidence_date");
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
	CONSTRAINT "seller_intent_current_pk" PRIMARY KEY("firm_id","dataset_version")
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
CREATE INDEX "seller_intent_history_firm_idx" ON "seller_intent_history" USING btree ("firm_id","dataset_version","changed_at");
