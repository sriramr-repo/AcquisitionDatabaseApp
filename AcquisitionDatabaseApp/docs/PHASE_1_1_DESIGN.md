# Phase 1.1 implementation note

## Outcome

Close the visual refresh on Overview, Research, and Firm Detail, and make Target
Explorer column preferences personal to each signed-in analyst and available on
their other devices. Preserve all existing dashboard routes, actions, data, and
the separate Outreach shortlist scope.

## Implementation

- Use the authenticated user ID as the preference owner, with a Postgres JSONB
  preference record and authenticated read/write API. Keep existing browser
  preferences as a one-time migration source for the current analyst.
- The credentials provider currently supports one configured email. Authenticate
  existing `users` table accounts first, retaining the configured credential as
  a backwards-compatible fallback, so distinct accounts can have distinct
  preference identities.
- Apply the existing shared visual system to Overview, Research, and Firm Detail
  with semantic layout classes and responsive styles; preserve existing content
  and controls.
- Add an additive Drizzle migration. Preview deployments use isolated database
  branches, and the normal deployment build does not run migrations.

## Acceptance

- Column changes survive sign-out, another browser/device, and a session refresh;
  separate user IDs have separate settings; unauthenticated writes are rejected.
- Existing column choices migrate once from local storage when no server record
  exists, and defaults remain usable if the API is temporarily unavailable.
- Overview, Research, and Firm Detail retain all current metrics, evidence,
  workflows, and links while adopting the Phase 1 visual system at mobile and
  desktop widths.
- Build and focused tests pass. Publish a preview for manual review; production
  promotion and database migration require the established release process.

## Risks and limits

The database migration must be applied to the isolated preview database before
testing saved preferences. Existing sessions are tied to their email identity;
users should retain stable emails or IDs so preferences remain attached to the
same analyst.
