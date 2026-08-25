CREATE TABLE "research_agent_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"firm_id" text NOT NULL,
	"dataset_version" text NOT NULL,
	"status" text DEFAULT 'QUEUED' NOT NULL,
	"source_capture_ids" jsonb NOT NULL,
	"source_set_hash" text NOT NULL,
	"prompt_version" text NOT NULL,
	"extraction_version" text NOT NULL,
	"model_provider" text NOT NULL,
	"model_name" text NOT NULL,
	"max_pages" integer NOT NULL,
	"max_tokens" integer NOT NULL,
	"timeout_seconds" integer NOT NULL,
	"requested_by" text,
	"error_message" text,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "research_observations" ADD COLUMN "source_capture_id" text;--> statement-breakpoint
ALTER TABLE "research_observations" ADD COLUMN "agent_job_id" text;--> statement-breakpoint
ALTER TABLE "research_observations" ADD COLUMN "evidence_excerpt" text;--> statement-breakpoint
ALTER TABLE "research_observations" ADD COLUMN "extraction_version" text;--> statement-breakpoint
ALTER TABLE "research_observations" ADD COLUMN "model_provider" text;--> statement-breakpoint
ALTER TABLE "research_observations" ADD COLUMN "model_name" text;--> statement-breakpoint
CREATE UNIQUE INDEX "research_agent_job_idempotency_idx" ON "research_agent_jobs" USING btree ("firm_id","dataset_version","source_set_hash","extraction_version");