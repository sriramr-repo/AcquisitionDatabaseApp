# Phase 2 implementation note

## User story

As an analyst, I can add or remove a firm from my personal Outreach shortlist in
Target Explorer. My Outreach tab shows only firms on my shortlist, while keeping
the existing shared outreach status, owner, and next-action fields visible.

## Decisions

- Shortlisting is a personal binary choice: **Shortlisted** or **Not shortlisted**.
  A firm is absent from the Outreach queue until the analyst explicitly adds it.
- Store membership by stable analyst ID and firm CRD, so choices survive dataset
  refreshes and do not leak between analysts. Only firms in the active dataset
  appear in the queue.
- Preserve `outreach_targets` as the existing shared workflow record. Shortlist
  membership does not change shared outreach status, assign an owner, create an
  activity, or send a message.
- Require authentication and the existing outreach eligibility policy when
  adding a firm. Always allow an analyst to remove their own shortlist entry,
  including if the firm's current eligibility changes.

## Acceptance criteria

- Target Explorer shows an accessible add/remove control for each eligible row.
- The current analyst's choices are reflected on Target Explorer and persist on
  another device. A second analyst's choices remain independent.
- Outreach is empty for an analyst with no shortlist entries and otherwise
  contains only that analyst's selected firms, with the existing workflow fields.
- ERA-only or otherwise ineligible firms cannot be added. Unshortlisting remains
  available after eligibility changes.
- Existing outreach status and activity APIs keep their current shared behavior.

## Delivery

Implement on a separate Phase 2 branch with an additive migration and a Vercel
preview. Apply the migration to the isolated preview database for manual testing;
production promotion and production migration are separate release actions.
