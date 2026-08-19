CREATE TABLE "alerts" (
	"alert_id" text PRIMARY KEY NOT NULL,
	"event_type" text,
	"severity" text,
	"message" text,
	"created_at" timestamp with time zone,
	"acknowledged_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "backup_metadata" (
	"backup_id" text PRIMARY KEY NOT NULL,
	"dataset_version" text,
	"created_at" timestamp with time zone,
	"status" text,
	"manifest" jsonb
);
--> statement-breakpoint
CREATE TABLE "change_intelligence" (
	"change_id" text PRIMARY KEY NOT NULL,
	"dataset_version" text,
	"firm_id" text,
	"event_type" text,
	"details" jsonb,
	"created_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "contacts" (
	"contact_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"contact_name" text,
	"title" text,
	"decision_maker_type" text,
	"email" text,
	"phone" text,
	"profile_url" text,
	"contact_confidence" text,
	"identity_confidence" text,
	"verification_status" text,
	"analyst_notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "dataset_versions" (
	"dataset_version" text PRIMARY KEY NOT NULL,
	"dataset_date" text,
	"score_version" text,
	"silver_rows" integer,
	"gold_rows" integer,
	"priority_counts" jsonb,
	"published_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "enrichment_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"status" text NOT NULL,
	"requested_by" text,
	"error_message" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"completed_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "research_evidence_captures" (
	"capture_id" text PRIMARY KEY NOT NULL,
	"source_id" text NOT NULL,
	"scrape_id" text,
	"extraction_method" text,
	"content_type" text,
	"content" text,
	"metadata" jsonb,
	"content_hash" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "firm_facts" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"total_aum" real,
	"discretionary_aum" real,
	"non_discretionary_aum" real,
	"total_account_count" integer,
	"average_account_size" real,
	"individual_hnw_share" real,
	"employee_count" integer,
	"advisory_employee_count" integer,
	"state_iar_count" integer,
	"has_item_11_disclosure" boolean,
	"regulatory_review_flag" boolean,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "firm_facts_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "firm_research" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"research_status" text DEFAULT 'NOT_STARTED' NOT NULL,
	"research_owner" text,
	"founder_name" text,
	"founder_role" text,
	"ownership_type" text,
	"ownership_summary" text,
	"succession_readiness_assessment" text,
	"investment_philosophy" text,
	"primary_custodian" text,
	"strategic_fit_assessment" text,
	"transition_feasibility" text,
	"integration_risks" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "firm_research_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "firm_scores" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"acquisition_score" real,
	"priority_category" text,
	"priority_readiness" text,
	"review_required" boolean,
	"component_scores" jsonb,
	"reason_codes" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "firm_scores_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "firms" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"name" text,
	"primary_business_name" text,
	"website_address" text,
	"organization_state" text,
	"sec_region" text,
	"sec_current_status" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "firms_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "research_observations" (
	"observation_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"source_id" text NOT NULL,
	"canonical_field" text NOT NULL,
	"proposed_value" text,
	"value_type" text NOT NULL,
	"confidence" text,
	"review_status" text DEFAULT 'PROPOSED' NOT NULL,
	"reviewer" text,
	"reviewed_at" timestamp with time zone,
	"review_notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "outreach_activities" (
	"activity_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"activity_type" text NOT NULL,
	"occurred_at" timestamp with time zone NOT NULL,
	"notes" text,
	"created_by" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "outreach_status_history" (
	"history_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"from_status" text,
	"to_status" text NOT NULL,
	"changed_by" text,
	"changed_at" timestamp with time zone DEFAULT now() NOT NULL,
	"notes" text
);
--> statement-breakpoint
CREATE TABLE "outreach_targets" (
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"status" text DEFAULT 'NOT_RESEARCHED' NOT NULL,
	"primary_contact_id" text,
	"assigned_to" text,
	"last_activity_at" timestamp with time zone,
	"next_action" text,
	"next_action_date" text,
	"notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "outreach_targets_firm_id_dataset_version_pk" PRIMARY KEY("firm_id","dataset_version")
);
--> statement-breakpoint
CREATE TABLE "pipeline_runs" (
	"run_id" text PRIMARY KEY NOT NULL,
	"dataset_version" text,
	"status" text,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"duration_seconds" real,
	"details" jsonb
);
--> statement-breakpoint
CREATE TABLE "pipeline_stages" (
	"stage_id" text PRIMARY KEY NOT NULL,
	"run_id" text,
	"stage_name" text,
	"status" text,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"duration_seconds" real,
	"details" jsonb
);
--> statement-breakpoint
CREATE TABLE "research_refresh_queue" (
	"queue_id" text PRIMARY KEY NOT NULL,
	"firm_id" text,
	"dataset_version" text,
	"reason" text,
	"status" text,
	"created_at" timestamp with time zone
);
--> statement-breakpoint
CREATE TABLE "research_sources" (
	"source_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"source_type" text NOT NULL,
	"source_url" text,
	"source_title" text,
	"source_authority" text,
	"accessed_at" timestamp with time zone,
	"retrieval_status" text,
	"content_hash" text,
	"field_supported" text,
	"source_notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" text PRIMARY KEY NOT NULL,
	"email" text NOT NULL,
	"password_hash" text NOT NULL,
	"name" text,
	"role" text DEFAULT 'analyst' NOT NULL,
	CONSTRAINT "users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
CREATE UNIQUE INDEX "firms_firm_dataset_idx" ON "firms" USING btree ("firm_id","dataset_version");