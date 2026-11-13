CREATE TABLE "analyst_outreach_shortlists" (
	"analyst_id" text NOT NULL,
	"firm_id" text NOT NULL,
	"added_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "analyst_outreach_shortlists_analyst_id_firm_id_pk" PRIMARY KEY("analyst_id","firm_id")
);
