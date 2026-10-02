export const sellerIntentDefinitions: Record<string, string> = {
  UNKNOWN: "No verified evidence currently establishes willingness or unwillingness.",
  SIGNAL_IDENTIFIED: "Credible indirect evidence suggests a transaction or transition discussion may be relevant, but it is not confirmed.",
  DIRECTLY_EXPRESSED: "An owner or authorized decision maker explicitly expressed openness to a sale, merger, succession, or strategic transaction.",
  ENGAGED_IN_DISCUSSION: "A substantive two-way discussion has occurred and has a next step.",
  FORMAL_PROCESS: "A verified organized sale, merger, or strategic-alternatives process is underway.",
  NOT_INTERESTED: "An owner or authorized decision maker explicitly stated they are not currently interested.",
  STALE: "A user manually marked a previously verified status as no longer reliable.",
  CONFLICTING: "Credible current evidence supports materially different conclusions.",
};

export const sellerIntentStatuses = Object.keys(sellerIntentDefinitions);
export const sellerIntentSourceTypes = ["OWNER_COMMUNICATION", "AUTHORIZED_REPRESENTATIVE", "OUTREACH_RESPONSE", "CALL", "MEETING", "AUTHORIZED_INTERMEDIARY", "NAMED_REFERRAL", "PUBLIC_FORMAL_PROCESS"];
