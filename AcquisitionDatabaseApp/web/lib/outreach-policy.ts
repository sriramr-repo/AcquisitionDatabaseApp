export type RegistrationEligibility = {
  is_registered?: boolean | null;
  is_era_only?: boolean | null;
};

export const ERA_OUTREACH_BLOCKED = "ERA-only firms are not eligible for outreach";

export function outreachAllowed(registration: RegistrationEligibility): boolean {
  // Historical SEC datasets intentionally carry unknown registration fields.
  // Preserve their existing workflow while failing closed for explicit ERA-only rows.
  return registration.is_registered !== false && registration.is_era_only !== true;
}
