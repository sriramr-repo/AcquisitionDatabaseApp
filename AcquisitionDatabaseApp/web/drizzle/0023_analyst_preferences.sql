CREATE TABLE "analyst_preferences" (
	"analyst_id" text NOT NULL,
	"preference_key" text NOT NULL,
	"preference_value" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "analyst_preferences_pk" PRIMARY KEY("analyst_id", "preference_key")
);
