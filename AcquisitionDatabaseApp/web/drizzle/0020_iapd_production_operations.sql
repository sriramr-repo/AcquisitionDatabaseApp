CREATE TABLE IF NOT EXISTS "iapd_feed_runs" (
	"run_id" text PRIMARY KEY NOT NULL,
	"requested_date" text NOT NULL,
	"selected_date" text,
	"status" text NOT NULL,
	"source_url" text,
	"source_hash" text,
	"attempts" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"result_counts" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"started_at" timestamp with time zone NOT NULL,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "iapd_feed_runs_started_idx" ON "iapd_feed_runs" ("started_at" DESC);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "iapd_live_batches" (
	"batch_id" text PRIMARY KEY NOT NULL,
	"status" text NOT NULL,
	"scope" text NOT NULL,
	"options" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"counts" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"checkpoint_crd" text,
	"started_at" timestamp with time zone NOT NULL,
	"completed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "iapd_live_jobs" (
	"job_id" text PRIMARY KEY NOT NULL,
	"batch_id" text,
	"individual_crd" text NOT NULL,
	"source_url" text NOT NULL,
	"parser_version" text NOT NULL,
	"priority_order" bigint NOT NULL,
	"status" text DEFAULT 'QUEUED' NOT NULL,
	"attempt_count" integer DEFAULT 0 NOT NULL,
	"max_attempts" integer DEFAULT 3 NOT NULL,
	"last_attempt_at" timestamp with time zone,
	"next_attempt_at" timestamp with time zone,
	"last_success_at" timestamp with time zone,
	"last_content_hash" text,
	"failure_reason" text,
	"result_summary" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "iapd_live_job_version_idx" ON "iapd_live_jobs" ("individual_crd","parser_version");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "iapd_live_job_queue_idx" ON "iapd_live_jobs" ("status","next_attempt_at","priority_order");
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS "iapd_manual_review_queue" (
	"review_id" text PRIMARY KEY NOT NULL,
	"individual_crd" text NOT NULL,
	"reason_code" text NOT NULL,
	"status" text DEFAULT 'OPEN' NOT NULL,
	"monthly_snapshot_id" text,
	"live_capture_id" text,
	"details" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "iapd_manual_review_open_idx" ON "iapd_manual_review_queue" ("status","reason_code","created_at" DESC);
