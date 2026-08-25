ALTER TABLE "research_observations" ADD COLUMN "source_chunk_id" text;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "max_content_chars" integer DEFAULT 120000 NOT NULL;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "max_chunk_chars" integer DEFAULT 6000 NOT NULL;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "max_chunks" integer DEFAULT 18 NOT NULL;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "attempt_count" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "max_attempts" integer DEFAULT 3 NOT NULL;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "next_attempt_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "last_error_category" text;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "worker_id" text;--> statement-breakpoint
ALTER TABLE "research_agent_jobs" ADD COLUMN "lease_expires_at" timestamp with time zone;