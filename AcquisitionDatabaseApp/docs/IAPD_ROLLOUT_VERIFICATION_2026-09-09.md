# IAPD rollout verification — September 9, 2026

## Release status

Implementation checkpoint: `828ab80`. Vercel deployment is Ready:
https://scm-ria-acquisition-dashboard-in906t2w5-srivercel.vercel.app

Production alias: https://scm-ria-acquisition-dashboard.vercel.app

The deployment was built from an isolated archive of the committed checkpoint, not the dirty working tree. This is a deployed incremental rollout, **not certification that every original acceptance criterion is complete**. Git push was not performed as part of this verification.

## Verified data

| Measure | Result |
|---|---:|
| Imported feed date | 2026-09-08 |
| Unique representatives | 439,159 |
| Current employment records | 447,094 |
| Current registration records | 839,232 |
| Disclosure records | 60,002 |
| Parse issues in validated feed | 0 |
| Duplicate representative ratio | 0 |
| Published firm universe | 17,018 |
| Firms with current representative links | 10,733 |
| Firms without current representative links | 6,285 |
| Sum of firm representative counts | 424,122 |
| Verified R2 firm bundles | 10,733 |

Source: https://reports.adviserinfo.sec.gov/reports/CompilationReports/IA_INDVL_Feed_09_08_2026.xml.zip

SHA-256: `997abde436cb288c8d9daaf4d8d07a8d5da37fee2da14090c15be9c5cf593ed0`.

The 424,122 count is a sum across firms, not a deduplicated national person count. Absence of a current representative link does not establish that a firm has no owner or principal.

The full feed stays in local DuckDB, with compressed firm bundles in R2. Neon holds compact summaries and workflow/audit records, following the revised storage requirement. Its last checked size was approximately 392 MB. The complete feed was deliberately not loaded into Neon's detailed person tables. Prior local data and R2 manifest references were preserved.

## Implemented behavior

- Monthly parsing tolerates namespace and nested-wrapper variations, missing optional values, duplicate persons, and multiple employer relationships; anomalies remain reportable.
- Recovery validates official feed URLs and ZIP/XML plausibility, uses bounded retries and official-link discovery, and preserves the prior successful data when retrieval fails.
- Live retrieval is restricted to IAPD individual pages through server-side Firecrawl; capture provenance and reconciliation remain separate from firm master facts.
- Batches expose deterministic selection, limits, freshness skipping, resume/retry state and per-person failures. Large-scale live execution is not complete.
- Reconciliation retains monthly baseline evidence and exposes conflicting live values. Equivalent date formats are normalized.
- Target Explorer adds AUM, state, representative-count, freshness, conflict and disclosure filters; firm rows remain dataset-scoped.
- Firm detail displays R2 representative details and evidence; Operations displays feed runs, job state and review reasons.
- Existing day-4 local refresh script includes IAPD recovery, local-store/R2 publication and a bounded live batch. No duplicate scheduler was created.

Migration `0020_iapd_production_operations.sql` was applied for `iapd_feed_runs`, `iapd_live_batches`, `iapd_live_jobs`, and `iapd_manual_review_queue`. Existing earlier migrations were retained.

## Live pilot

Three representative jobs were exercised, including failure retries and freshness skipping. The final repeat skipped all three as fresh. Current pilot jobs have no failed or retry-pending state. Two review items remain open: multiple current employers and a registration-date discrepancy. One equivalent-date-format review item was resolved with history retained.

These figures describe the pilot only. They do not mean the remaining national person universe has been crawled, nor that every person has contact details.

## Verification

- Python IAPD/CLI/ADV/security/seller-intent suite: 102 passed, 1 optional PostgreSQL test skipped in the main run.
- The optional PostgreSQL test was then run separately: 1 passed, isolated transaction rolled back.
- Node component tests: 8 passed.
- Production Next.js build: passed locally and Vercel deployment Ready.
- Query smoke tests: passed for dataset alignment, pagination uniqueness, filters, four sort modes, empty search and firm details.
- Local authenticated browser: login, Overview, combined filters, empty state and Operations checked.
- Production authenticated browser: Overview, Target Explorer, firm detail, Research, Outreach and Operations rendered successfully.
- Production combined filter (under $200M, MA, has representatives): 110 filtered out of 17,018, three active filters, September 8 freshness date.
- Production firm 130601: two representatives loaded from Cloudflare R2.
- Production Operations: September 8 feed success, three fresh-skipped pilot jobs, two open review items.
- Production Firecrawl environment variable was added without exposing its value.

## Remaining acceptance gaps and risks

1. Full-universe live-page processing has not run; only the controlled pilot has completed. Do not launch hundreds of thousands of captures without verifying service quota and storage growth.
2. A detailed prior-versus-current report of new/disappeared people and employment/registration/disclosure changes remains to be completed; aggregate counts alone are insufficient.
3. The entire day-4 refresh has not been executed end-to-end after the script change. Its shell validation and scheduler configuration were checked; a live full pipeline run was avoided to protect the existing active SEC dataset.
4. Not every requested browser scenario was exercised on both local and production builds. In particular, the full production sort/pagination interaction matrix and conflict expansion still need browser-level acceptance, beyond query tests.
5. Two employment/registration review items remain unresolved; evidence must not be silently changed to clear them.
6. The legacy quality-report query still reads the detailed Neon snapshot table; it needs alignment with the newer local-feed/compact-summary architecture before it can be treated as the latest-feed report.
7. The representative badge currently describes the `active_ag_registration` flag as Active/Not active alongside state registration rows. The meaning should be clarified before interpreting it as overall IAR registration status.
8. Large live runs need additional validation of concurrent claiming, interruption/retry behavior, and capture storage growth before full-universe execution.

No scoring formulas, Priority logic, or firm-master source-of-truth rules were intentionally changed in this rollout.

## Exact committed change inventory

Paths below are relative to AcquisitionDatabaseApp. Existing ADV dependencies were included so the deployed commit contains everything its pages import.

```text
deploy/production-refresh.env.example
deploy/production-refresh.sh
docs/IAPD_REPRESENTATIVE_ENRICHMENT.md
src/adv_facts.py
src/adv_ocr.py
src/cli.py
src/fact_catalog.py
src/iapd.py
src/iapd_batch.py
src/iapd_live.py
src/iapd_reconciliation.py
src/iapd_recovery.py
src/seller_intent.py
tests/test_adv_facts.py
tests/test_dashboard_adv_security.py
tests/test_dashboard_office_postal.py
tests/test_iapd_live_postgres.py
tests/test_iapd_production.py
tests/test_iapd_resilience.py
tests/test_seller_intent.py
web/app/api/adv/[firmId]/refresh/route.ts
web/app/api/seller-intent/[firmId]/route.ts
web/app/api/targets/route.ts
web/app/components/AdvDetails.tsx
web/app/components/AdvIndicators.tsx
web/app/components/RepresentativeEvidence.tsx
web/app/components/SellerIntentStatus.tsx
web/app/data-dictionary/page.tsx
web/app/firms/[firmId]/AdvSellerControls.tsx
web/app/firms/[firmId]/page.tsx
web/app/globals.css
web/app/layout.tsx
web/app/operations/page.tsx
web/app/targets/page.tsx
web/drizzle/0016_adv_facts_and_seller_intent.sql
web/drizzle/0017_adv_extraction_pipeline.sql
web/drizzle/0018_adv_job_leases.sql
web/drizzle/0019_main_office_postal_code.sql
web/drizzle/0020_iapd_production_operations.sql
web/drizzle/meta/_journal.json
web/lib/adv-visibility.ts
web/lib/queries.ts
web/lib/schema.ts
web/lib/seller-intent.ts
web/middleware.ts
web/tests/adv-queries-smoke.cjs
web/tests/adv-visibility.test.cjs
web/tests/iapd-evidence.test.cjs
```
