CREATE TABLE "iapd_firm_summary_batches" (
	"snapshot_id" text NOT NULL,
	"member_name" text NOT NULL,
	"processed_at" timestamp with time zone NOT NULL,
	CONSTRAINT "iapd_firm_summary_batches_snapshot_id_member_name_pk" PRIMARY KEY("snapshot_id","member_name")
);
