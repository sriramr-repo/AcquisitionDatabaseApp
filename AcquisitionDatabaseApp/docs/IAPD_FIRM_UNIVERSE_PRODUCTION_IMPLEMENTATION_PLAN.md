# Canonical IAPD Firm-Universe Production Implementation Plan

## 1. Objective

Activate the canonical IAPD SEC/state firm universe in production without
allowing staging credentials, an unvalidated source snapshot, or a partial
refresh to replace the active dataset.

The first activation should use the already-shadowed November 7, 2026 snapshot
unless the owner explicitly chooses to shadow and approve a newer snapshot.
The November 7 snapshot-specific reconciliation is:

- 43,918 canonical CRDs
- 33,615 registered CRDs
- 10,303 ERA-only CRDs
- 240 dual-registered CRDs
- 188,781 registration relationships
- 43,918 office records
- 30,581 registered Priority A/B/C acquisition targets

These values are evidence for this snapshot, not permanent hard-coded universe
requirements.

## 2. Current State and Blocking Conditions

Completed:

- Migration `0022_iapd_firm_universe` passed audit and staging application.
- PostgreSQL and application integration tests passed.
- The November 7 sources passed gzip, root, CRD, identity, and published-XSD
  validation.
- The isolated Silver/Gold refresh reproduced every runbook baseline.
- ERA-only targeting is blocked in the publisher, API, Virtual SDR, and UI.

Production execution is currently blocked because:

1. The active launch agent supplies a localhost `PUBLISHER_DATABASE_URL`, and
   the last scheduled run failed because no local PostgreSQL server exists.
2. `deploy/production-refresh.env` contains R2 configuration but no production
   `DATABASE_URL` or `PUBLISHER_DATABASE_URL`.
3. The latest official manifest has advanced to November 8. The production
   refresh currently always selects the latest manifest, so it cannot
   reproduce the November 7 shadow run.
4. No production maintenance window, provider snapshot, tested database
   restore, execution operator, or rollback owner has been recorded.
5. The implementation remains uncommitted and undeployed.

### 2.1 Deployment topology

Vercel hosts only the Next.js dashboard and its server-side routes. It reads
the active compact dataset from hosted PostgreSQL/Neon and retrieves protected
firm-detail bundles from Cloudflare R2. It must not run the IAPD downloads,
XML/XSD validation, DuckDB/Parquet processing, dashboard publication, OCR, or
R2 upload pipeline.

The protected refresh host remains the data-plane worker. Its scheduled job
builds and validates the canonical dataset, publishes compact rows to the same
hosted PostgreSQL database consumed by Vercel, and uploads immutable bundles
to R2. PostgreSQL and R2 are therefore the promotion boundary between the
refresh host and Vercel; Vercel's ephemeral filesystem is not an artifact or
rollback store.

## 3. Design Decisions

### 3.1 Vercel and refresh-host releases are separate

Use independent configuration and release gates for:

- **Vercel application:** `DATABASE_URL`, authentication settings, and
  read-only R2 credentials needed by protected server routes.
- **Protected refresh host:** `DATABASE_URL`, `PUBLISHER_DATABASE_URL`, and R2
  write credentials needed by migrations, publication, and bundle activation.

Do not place `PUBLISHER_DATABASE_URL`, source-download logic, DuckDB files, or
R2 write credentials in the Vercel deployment. Prefer separate least-privilege
R2 credentials even when both environments use the same bucket.

Vercel builds must remain deterministic and must not run database migrations
or refresh jobs. Run migration `0022` as an explicit operator step against the
verified hosted database before promoting application code that queries its
new columns.

### 3.2 Production database selection must fail closed

In production, both `DATABASE_URL` and `PUBLISHER_DATABASE_URL` must be present
in the permission-restricted production environment file and must resolve to
the same non-local host, port, database, and `public` schema.

Remove the production script's ability to load `web/.env.local` when either
database variable is missing. That file is the designated staging
configuration and must never be a production fallback.

The launch agent should provide `SCM_ENV`, `SCM_DATA_DIR`, `SCM_PYTHON`, and an
explicit `SCM_REFRESH_ENV_FILE`. Database credentials should have one owner and
one source: the mode-`0600` production environment file. Remove the stale
localhost publisher URL from the launch agent.

### 3.3 The first activation must be reproducible

Add an explicit snapshot-selection interface to the production refresh. It
must support:

- Default mode: resolve the current same-date SEC/state pair from the official
  manifest.
- Pinned mode: resolve official filenames from an explicitly approved snapshot
  date or reviewed activation manifest.

Pinned mode must still construct URLs on
`https://reports.adviserinfo.sec.gov`, require the expected filenames, verify
gzip integrity, roots, generation dates, CRDs, identities, published XSDs, and
source hashes, and refuse redirects away from the official host. It must not
accept caller-supplied arbitrary URLs.

Persist a reviewed, non-secret activation manifest for `iapdfirm20261107`
containing:

- Dataset version and snapshot date
- Exact official SEC/state filenames and URLs
- Source and XSD SHA-256 hashes
- Parser/schema versions
- Snapshot-specific reconciliation counts
- Shadow report identifier and creation time

The count fields are comparison evidence. Classification and row production
must continue to come from parsed source records.

### 3.4 Discovery must occur once per run

Refactor production discovery so `production_refresh` resolves one immutable
feed pair and passes it into the staged runner. The staged runner must not
silently rediscover a newer manifest between run creation and download.

Record discovery mode (`latest_manifest` or `pinned_snapshot`), snapshot date,
official URLs, hashes, and schema hashes in the run manifest and Bronze
reconciliation report.

### 3.5 Promotion remains validation-gated

Continue using the existing clean-room staging path. Do not publish to
PostgreSQL until all Bronze, Silver, Gold, export, reconciliation, and
eligibility gates pass.

The PostgreSQL publisher remains one transaction. Existing dataset versions
and files must not be overwritten or deleted. `dataset_versions.published_at`
selects the active dashboard dataset only after publication succeeds.

## 4. Implementation Work

### Workstream A: production target isolation

Likely files:

- `deploy/production-refresh.sh`
- `deploy/production-refresh.env.example`
- `deploy/launchd/com.scm.ria.production-refresh.plist.template`
- `src/refresh_preflight.py`
- Production/preflight tests

Changes:

1. Require both database variables when `SCM_ENV=PROD`.
2. Prohibit `web/.env.local` fallback in production.
3. Require identical migration and publisher database identities.
4. Keep localhost rejection and ledger validation.
5. Print only redacted target identity and a stable non-secret fingerprint.
6. Document the single production credential source and mode requirement.

Acceptance criteria:

- Missing or mismatched database variables stop before source download.
- Staging and localhost targets are rejected.
- Secrets never appear in logs or error messages.
- Dry-run performs read-only checks only.

### Workstream B: snapshot pinning and activation manifest

Likely files:

- `src/iapd_firms.py`
- `src/production.py`
- `src/cli.py`
- `deploy/production-refresh.sh`
- A non-secret activation-manifest directory
- Importer and production-operation tests

Changes:

1. Add a typed feed-pair resolver for latest and pinned modes.
2. Add a CLI option such as `--firm-snapshot-date` or
   `--firm-activation-manifest`; choose one public contract and document it.
3. Pass the resolved feed pair through the entire staged-refresh call instead
   of rediscovering it.
4. Compare downloaded hashes and reconciliation results with the reviewed
   activation manifest.
5. Refuse missing files, changed hashes, mismatched dates, or count
   discrepancies until reviewed; never force counts to match.
6. Preserve quarantine artifacts outside active dataset paths.

Acceptance criteria:

- A November 7 pinned dry run selects only the two November 7 official files.
- A manifest advancing during a run cannot change the selected snapshot.
- Hostile URLs and altered hashes fail before normalization.
- Existing latest-manifest behavior remains available for later monthly runs.

### Workstream C: production evidence and rollback artifacts

Likely files:

- Deployment documentation
- Backup/restore operator checklist
- Optional report-generation helper using existing backup APIs

Changes:

1. Record production database fingerprint, migration ledger, dataset counts,
   local active version, and R2 manifest before execution.
2. Create and verify three independent recovery artifacts:
   - Provider-supported database snapshot or branch
   - Custom-format PostgreSQL dump with SHA-256 and `pg_restore --list`
   - Existing local metadata/DuckDB/Bronze/Gold backup with verified manifest
3. Restore the database dump into an isolated provider branch/database and the
   local backup into an isolated directory before accepting the backup gate.
4. Record identifiers, paths, hashes, timestamps, operator, and restore owner.

Acceptance criteria:

- Both restore paths are tested without touching active production.
- A failed restore blocks migration.
- Previous snapshots and R2 manifests remain available.

### Workstream D: production smoke and rollback checks

Add a reproducible post-publication check that reports, without changing data:

- Migration ledger and schema objects
- Source, registered, ERA-only, dual, and acquisition-target counts
- Silver/Gold uniqueness and row equality
- ERA hard-exclusion and outreach-target absence
- Representative employer-CRD coverage
- Dashboard registered/ERA/SEC/state/dual filters
- API rejection of ERA outreach and Virtual SDR creation
- R2 manifest coverage and current dataset identity
- Operational alerts and failed stages

### Workstream E: Vercel release configuration

Likely files and systems:

- `web/vercel.json`
- `web/.env.example` and deployment documentation
- Vercel project environment settings
- Vercel production and preview deployments

Changes and checks:

1. Keep `web/vercel.json` build-only; do not attach ingestion or migration to
   `npm run build`.
2. Configure the production `DATABASE_URL` to the same verified hosted
   database that receives publisher output.
3. Configure server-only authentication and read-only R2 credentials in
   Vercel; do not expose them through `NEXT_PUBLIC_*` variables.
4. Verify previews cannot mutate or accidentally target production data. Use
   a separate preview database or disable mutating workflows in previews.
5. Exercise the production alias after data publication and retain the prior
   Vercel deployment for application rollback.

Acceptance criteria:

- Vercel serves the new classification fields without local filesystem state.
- A Vercel build or rollback cannot start a refresh or change the active R2
  manifest.
- Server-only credentials are absent from client bundles and build logs.
- Application and data-plane rollback can be performed independently.

## 5. Test Plan

### Unit and failure-path tests

- Production environment rejects missing, localhost, staging, and mismatched
  migration/publisher targets.
- Pinned-date resolution constructs only official filenames and URLs.
- Manifest movement after resolution does not alter the selected feeds.
- Changed source hash, XSD, root, date, CRD, or legal identity fails closed.
- No fallback to staging configuration is possible in production.
- Snapshot-specific counts are compared but never used to manufacture rows.

### Integration tests

- Run PostgreSQL tests against an approved isolated DSN using temporary tables
  and rollback-only transactions.
- Repeat the real November 7 clean-room refresh through the new public pinned
  interface and reproduce the Stage 5 report.
- Exercise failed stages and prove the prior dataset, dashboard, R2 manifest,
  person bundles, research, seller intent, and outreach remain active.
- Test database and local restores in isolated targets.

### Required verification

```bash
uv run pytest -q
cd web && node --test tests/*.test.cjs
cd web && npm run build
```

Docker integration remains prohibited unless separately authorized.

## 6. Production Runbook

### Gate 1: freeze and identify

1. Approve the reviewed commit and exact snapshot mode.
2. Assign execution and rollback owners and a maintenance window.
3. Pause the launch agent so a scheduled run cannot overlap.
4. Configure the production environment file with mode `0600`.
5. Remove the stale localhost database value from the launch agent.
6. Record the redacted production database identity and baseline counts.
7. Confirm the active migration is `0021` and `0022` is unapplied.
8. Record the current Vercel production deployment, production alias, and
   redacted database/R2 environment identities.

Stop for any ambiguous target, unexpected ledger, or existing `0022` schema
drift.

### Gate 2: backup and restore proof

1. Create the provider snapshot.
2. Create and hash the PostgreSQL custom dump.
3. Create and verify the local application backup.
4. Restore both into isolated targets.
5. Reconcile restored migration history and counts with production baselines.

Stop if any backup, hash, catalog, restore, or count check fails.

### Gate 3: schema migration

From `web/`, with the approved production environment exported:

```bash
npm run db:migrate
```

Expected result: one new Drizzle ledger entry for
`0022_iapd_firm_universe`, 14 nullable columns, and one valid registration
index. Existing records and historical null classifications remain unchanged.

Run the repository's read-only preflight after migration. Stop for ledger,
identity, table, or connectivity discrepancies.

### Gate 4: canonical refresh and publication

1. Execute the approved pinned/latest staged refresh.
2. Validate source identity and reconciliation before promotion.
3. Confirm Silver/Gold equality, eligibility, priority, representative, and
   ERA invariants.
4. Publish the validated dashboard dataset in one PostgreSQL transaction.
5. Publish related ADV/IAPD/R2 artifacts only after their preceding gates
   succeed.

Stop before publication if the source differs from the approved shadow
snapshot or any discrepancy is unexplained.

### Gate 5: Vercel application promotion

1. Produce and verify the same production Next.js build used by Vercel.
2. Deploy a preview against an isolated preview database, or keep all mutating
   workflows disabled while it uses production read-only data.
3. Confirm the deployment contains no migration, refresh, or R2-upload step.
4. Promote the reviewed deployment to the production alias.

Stop if Vercel targets an unexpected database/bucket, exposes a server secret,
or the preview can mutate production.

### Gate 6: post-publication verification

1. Run the production smoke report.
2. Confirm dashboard cards distinguish registered firms and acquisition
   targets.
3. Confirm Target Explorer defaults to registered firms and all registration
   filters return expected counts.
4. Attempt ERA outreach and Virtual SDR creation with a controlled test firm;
   require API rejection and hidden UI controls.
5. Confirm monitoring, alerts, R2 publication, person bundles, and prior
   snapshots remain available.
6. Resume the launch agent only after operator and rollback-owner sign-off.
7. Run these checks through the Vercel production alias, not only against a
   local Next.js server.

## 7. Rollback Strategy

- **Before migration:** stop with no database change.
- **After migration but before publication:** leave the additive nullable
  schema in place and correct the application/configuration; restore the
  provider snapshot only for demonstrated schema corruption.
- **During failed local refresh:** the prior dataset remains active; use the
  verified local backup if any active artifact changed unexpectedly.
- **During failed PostgreSQL publication:** rely on the publisher transaction;
  verify no partial dataset became active.
- **After successful publication with failed smoke checks:** reactivate the
  prior verified dataset or restore the provider snapshot according to the
  recorded decision point. Do not delete the new snapshot while diagnosing.
- **Vercel application regression:** roll the production alias back to the
  prior compatible Vercel deployment. Do not roll back or restore data merely
  because the application deployment failed.
- **R2 failure:** keep the prior manifest active and block completion.

Physical column removal is not the preferred rollback because it destroys new
classification data. Application rollback can tolerate the additive schema.

## 8. Explicit Non-Goals

- Do not redesign scoring, AUM bands, research, seller intent, or Virtual SDR.
- Do not backfill historical registration classifications by inference.
- Do not make the 33,615 count a permanent assertion.
- Do not use name-based firm or representative joins.
- Do not delete or overwrite prior snapshots.
- Do not combine configuration, migration, refresh, deployment, and smoke
  verification into one unreviewed operation.

## 9. Definition of Done

Implementation is ready for a separate production-execution approval only
when:

- Production database identity is explicit, non-local, and distinct from the
  designated staging target.
- The snapshot mode and reviewed activation manifest are approved.
- All tests and the same-snapshot shadow refresh pass.
- Provider, PostgreSQL, and local restore procedures are proven.
- The migration and post-publication commands are reviewed.
- Maintenance window, execution operator, rollback owner, and stop conditions
  are recorded.
- The production preflight returns `passed` without exposing secrets.
