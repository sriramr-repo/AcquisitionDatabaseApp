CREATE TABLE "iapd_individual_aliases" (
	"alias_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"alias_name" text NOT NULL,
	"first_name" text,
	"middle_name" text,
	"last_name" text,
	"suffix" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_branch_locations" (
	"branch_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"employment_id" text,
	"individual_crd" text NOT NULL,
	"employer_firm_crd" text,
	"branch_name" text,
	"address_line_1" text,
	"address_line_2" text,
	"city" text,
	"state" text,
	"postal_code" text,
	"country" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_changes" (
	"change_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"event_type" text NOT NULL,
	"details" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_current_employments" (
	"employment_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"employer_firm_crd" text,
	"employer_name" text,
	"address_line_1" text,
	"address_line_2" text,
	"city" text,
	"state" text,
	"postal_code" text,
	"country" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_current_registrations" (
	"registration_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"employment_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"authority" text,
	"category" text,
	"status" text,
	"status_date" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_disclosure_flags" (
	"disclosure_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"reg_action" boolean,
	"criminal" boolean,
	"bankrupt" boolean,
	"civil_judgment" boolean,
	"bond" boolean,
	"judgment" boolean,
	"investigation" boolean,
	"customer_complaint" boolean,
	"termination" boolean,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_employment_history" (
	"history_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"organization_name" text,
	"city" text,
	"state" text,
	"from_date" text,
	"to_date" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_other_businesses" (
	"other_business_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"description" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_previous_registrations" (
	"previous_registration_id" text PRIMARY KEY NOT NULL,
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"employer_firm_crd" text,
	"employer_name" text,
	"authority" text,
	"category" text,
	"status" text,
	"begin_date" text,
	"end_date" text,
	"address_line_1" text,
	"address_line_2" text,
	"city" text,
	"state" text,
	"postal_code" text,
	"country" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_snapshot_members" (
	"snapshot_id" text NOT NULL,
	"individual_crd" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "iapd_individual_snapshot_members_snapshot_id_individual_crd_pk" PRIMARY KEY("snapshot_id","individual_crd")
);
--> statement-breakpoint
CREATE TABLE "iapd_individual_snapshots" (
	"snapshot_id" text PRIMARY KEY NOT NULL,
	"snapshot_date" text NOT NULL,
	"source_url" text NOT NULL,
	"source_file_name" text NOT NULL,
	"source_zip_path" text,
	"content_hash" text NOT NULL,
	"status" text NOT NULL,
	"individual_count" integer,
	"change_summary" jsonb,
	"downloaded_at" timestamp with time zone,
	"parsed_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "iapd_individuals" (
	"individual_crd" text PRIMARY KEY NOT NULL,
	"first_name" text,
	"middle_name" text,
	"last_name" text,
	"suffix" text,
	"full_name" text,
	"active_ag_registration" boolean,
	"composite_link" text,
	"last_snapshot_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_alias_snapshot_crd_idx" ON "iapd_individual_aliases" USING btree ("snapshot_id","individual_crd","alias_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_branch_firm_idx" ON "iapd_individual_branch_locations" USING btree ("snapshot_id","employer_firm_crd","branch_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_change_snapshot_idx" ON "iapd_individual_changes" USING btree ("snapshot_id","event_type","individual_crd");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_current_employment_firm_idx" ON "iapd_individual_current_employments" USING btree ("snapshot_id","employer_firm_crd","employment_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_current_employment_crd_idx" ON "iapd_individual_current_employments" USING btree ("snapshot_id","individual_crd","employment_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_current_registration_crd_idx" ON "iapd_individual_current_registrations" USING btree ("snapshot_id","individual_crd","registration_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_disclosure_crd_idx" ON "iapd_individual_disclosure_flags" USING btree ("snapshot_id","individual_crd","disclosure_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_employment_history_crd_idx" ON "iapd_individual_employment_history" USING btree ("snapshot_id","individual_crd","history_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_other_business_crd_idx" ON "iapd_individual_other_businesses" USING btree ("snapshot_id","individual_crd","other_business_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_previous_registration_crd_idx" ON "iapd_individual_previous_registrations" USING btree ("snapshot_id","individual_crd","previous_registration_id");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_snapshot_member_crd_idx" ON "iapd_individual_snapshot_members" USING btree ("snapshot_id","individual_crd");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_snapshot_hash_idx" ON "iapd_individual_snapshots" USING btree ("content_hash");--> statement-breakpoint
CREATE UNIQUE INDEX "iapd_snapshot_date_idx" ON "iapd_individual_snapshots" USING btree ("snapshot_date");