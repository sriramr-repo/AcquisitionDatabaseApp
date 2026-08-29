CREATE TABLE "virtual_sdr_artifacts" (
	"artifact_id" text PRIMARY KEY NOT NULL,
	"run_id" text NOT NULL,
	"version" integer NOT NULL,
	"status" text DEFAULT 'DRAFT' NOT NULL,
	"content" jsonb NOT NULL,
	"source_ids" jsonb NOT NULL,
	"confidence" text,
	"quality_status" text NOT NULL,
	"r2_key" text,
	"r2_etag" text,
	"storage_error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "virtual_sdr_quality_checks" (
	"check_id" text PRIMARY KEY NOT NULL,
	"run_id" text NOT NULL,
	"artifact_id" text NOT NULL,
	"check_type" text NOT NULL,
	"status" text NOT NULL,
	"score" real,
	"details" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "virtual_sdr_reviews" (
	"review_id" text PRIMARY KEY NOT NULL,
	"run_id" text NOT NULL,
	"artifact_id" text NOT NULL,
	"decision" text NOT NULL,
	"reviewer" text NOT NULL,
	"notes" text,
	"edited_content" jsonb,
	"resume_status" text DEFAULT 'PENDING' NOT NULL,
	"langgraph_resume_run_id" text,
	"error_message" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "virtual_sdr_runs" (
	"run_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"status" text DEFAULT 'REQUESTED' NOT NULL,
	"input_hash" text NOT NULL,
	"workflow_version" text NOT NULL,
	"prompt_version" text NOT NULL,
	"model_provider" text NOT NULL,
	"model_name" text NOT NULL,
	"langgraph_thread_id" text,
	"langgraph_run_id" text,
	"latest_artifact_id" text,
	"requested_by" text,
	"error_message" text,
	"trace_id" text,
	"model_usage" jsonb,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "virtual_sdr_artifact_version_idx" ON "virtual_sdr_artifacts" USING btree ("run_id","version");--> statement-breakpoint
CREATE UNIQUE INDEX "virtual_sdr_quality_check_idx" ON "virtual_sdr_quality_checks" USING btree ("run_id","artifact_id","check_type");--> statement-breakpoint
CREATE UNIQUE INDEX "virtual_sdr_run_idempotency_idx" ON "virtual_sdr_runs" USING btree ("firm_id","dataset_version","input_hash","workflow_version");
