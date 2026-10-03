# IAPD representative enrichment

## Recovery and reconciliation v2

For a missing/blocked monthly URL, explicitly discover the current official
compilation link and optionally refresh a bounded set of known individual CRDs:

```bash
python3 -m src.iapd_recovery --database-url "$PUBLISHER_DATABASE_URL" --crd 1015132 --limit 10
python3 -m src.iapd_recovery --database-url "$PUBLISHER_DATABASE_URL" --live-only --crd 1015132
```

The compilation's published date can differ from the fourth-of-month scheduler
date. Recovery follows only HTTPS individual-feed links on the official report
host. A blocked download remains unavailable; forcing a run does not guarantee
access or bypass a challenge. Live requests are sequential, bounded to at most
100 explicitly supplied CRDs, and retry transient failures three times.

Live parsing requires an explicitly identified matching CRD. Generic footer
phones and navigation URLs are not treated as representative contact details.
Responses are size bounded. Failed recovery attempts are written to the existing
import-issues table; previous evidence remains available. Each successful capture
retains its own timestamp and hash, even when the same page is retrieved again.

Reconciliation v3 preserves all monthly employer relationships, normalizes
equivalent ISO and U.S. registration-date formats, and keeps both
values when live evidence conflicts. A monthly source older than 45 days or live
source older than 30 days is partial. Exact CRDs are required for firm linking;
name-only matches are not promoted. Contact values include source identifiers
and observation timestamps in the effective-fields provenance object. The
dashboard overlays reconciliation onto both hosted and R2 representative details,
and exposes expandable contact, branch, disclosure, and conflict information.

Migration `0020_iapd_production_operations.sql` adds compact feed-run, live-batch,
live-job, and manual-review control-plane tables. Rebuilding reconciliation is
non-destructive and does not remove snapshot history.

The monthly SEC IAPD compilation report is the dashboard's person-level
enrichment source. It is a snapshot feed, not a live IAPD API substitute.

On the fourth day of each month, the production wrapper requests:

```text
https://reports.adviserinfo.sec.gov/reports/CompilationReports/IA_INDVL_Feed_MM_DD_YYYY.xml.zip
```

The job retains the validated ZIP under `data/iapd/raw/`, records its source URL
and SHA-256 hash, and streams the complete feed into local DuckDB and Parquet.
A duplicate snapshot date or file hash is skipped.

The import captures individual CRD and names, current employer firm CRD/name,
business and branch addresses supplied by the feed, current and prior
registration details, employment history, other businesses, and the feed's
disclosure flags. Current employer firm CRD is the only firm-link key; no
person-level value overwrites the SEC firm master, Silver, Gold, or research
records.

Each recovery is auditable through `iapd_feed_runs`. Compact firm summaries are
published to Neon for filtering; complete person and employment rows remain in
local DuckDB/Parquet and firm-level compressed bundles in R2. Parse anomalies
are retained in `iapd_import_issues`; missing CRDs, missing names, duplicate
people, malformed XML, empty ZIPs, and unexpected file contents are never
silently accepted.

## Live IAPD fallback

When the monthly ZIP is missing or blocked, the scheduled job returns
`fallback_required` without failing the completed firm refresh. A targeted
operator action can capture a specific public IAPD individual page through
server-side Firecrawl:

```bash
python3 -m src.cli iapd-live-crawl \
  --database-url "$PUBLISHER_DATABASE_URL" \
  --crd 12345
```

The capture retains the raw bounded response, URL, retrieval time, SHA-256,
parser version, confidence, and normalized labelled fields in
`iapd_live_captures` and `iapd_individual_live_enrichments`. It does not alter
the monthly snapshot or firm master. `iapd_individual_reconciliations` produces
the dashboard's effective view: monthly data remains the baseline for employer
and registrations; live data may fill contact fields; conflicts are visible
rather than overwritten.

Rebuild a representative's derived effective view, or inspect recent anomalies,
without changing source data:

```bash
python3 -m src.cli iapd-reconcile --database-url "$PUBLISHER_DATABASE_URL" --crd 12345
python3 -m src.cli iapd-reconcile --database-url "$PUBLISHER_DATABASE_URL" --all --limit 100
python3 -m src.cli iapd-audit --database-url "$PUBLISHER_DATABASE_URL"
```

Freshness values are `monthly_confirmed`, `live_confirmed`, `partial`,
`conflict`, and `missing`. Firecrawl is server-side only and a missing API key,
blocked page, malformed response, or mismatched CRD is recorded as unavailable;
it never creates a guessed person-to-firm join.

For a deliberate off-schedule backfill, run:

```bash
python3 -m src.iapd refresh --database-url "$PUBLISHER_DATABASE_URL" --date 2026-08-04 --force
```

Normal scheduled runs omit `--force` and skip safely outside the fourth day.

## Production recovery and live enrichment

The day-4 production wrapper now uses the recovery orchestrator. It tries the
expected dated compilation URL first. If that request is blocked, missing, or
invalid, Firecrawl reads the official IAPD compilation page and supplies only
links matching the exact `reports.adviserinfo.sec.gov` representative-feed
pattern. The newest candidate is fully parsed and checked before publication.

A candidate is quarantined under `data/iapd/quarantine/` when it is empty,
duplicate-heavy, structurally incomplete, or implausibly different from the
last local snapshot. A failed recovery leaves the previous DuckDB store and R2
manifest active. `iapd_feed_runs` retains attempted URLs, status, source hash,
and count results. Operational statuses are `success`, `fallback_success`,
`failed_preserved_previous`, and `no_new_feed`.

Force official discovery and import compact filter metadata:

```bash
python3 -m src.cli iapd-refresh \
  --database-url "$PUBLISHER_DATABASE_URL" --force --discover-latest
```

The full national feed remains in local DuckDB/Parquet. Firm-level compressed
bundles are activated in R2 only after their content hashes and manifest pass.
Neon remains the control plane and stores compact firm summaries, workflow,
freshness, conflict, and audit records. This avoids exceeding the hosted
database storage limit while keeping all dashboard firms queryable.

Compare an activated local snapshot with its preserved predecessor:

```bash
python3 -m src.iapd_local compare-snapshots \
  --current-database data/iapd/local/datasets/ia08032026_0/iapd.duckdb \
  --previous-database data/iapd/local/datasets/ia08032026_0.previous/iapd.duckdb \
  --report-path data/iapd/local/changes/ia08032026_0_2026-09-08.json
```

Omitting `--previous-database` emits a valid baseline report. The day-4 job
writes the comparison automatically, validates it, and publishes compact
dashboard-firm summaries to Neon before publishing R2 bundles. Reports
contain aggregate changes and bounded representative-CRD samples; a change is
not interpreted as misconduct, termination, ownership, or seller intent.

Validate a report without opening a database connection:

```bash
python3 -m src.iapd_change_publisher publish \
  --report-path data/iapd/local/changes/ia08032026_0_2026-09-08.json \
  --dry-run
```

Run a bounded batch for representatives linked to current dashboard firms:

```bash
python3 -m src.cli iapd-live-batch \
  --database-url "$PUBLISHER_DATABASE_URL" \
  --local-database data/iapd/local/datasets/ia08032026_0/iapd.duckdb \
  --limit 25 --workers 2 --freshness-days 30
```

Use repeated `--crd` options for selected representatives. `--resume` retries
eligible queued work from prior interrupted batches. `--all` explicitly opts
into the national person universe and must still be used with a bounded
`--limit`; it never creates arbitrary-URL crawl access. A scheduled run uses
`IAPD_LIVE_BATCH_SIZE`, `IAPD_LIVE_WORKERS`, and
`IAPD_LIVE_FRESHNESS_DAYS`. Set the batch size to `0` to disable the live
follow-up without disabling the monthly compilation import.

Each live job records attempts, last success, next retry, safe failure reason,
source URL, parser version, and result summary. Existing successful captures
survive later failures. Monthly evidence remains authoritative for employment,
registration, and disclosures. Live evidence fills exact-CRD contact gaps.
Conflicting names, employer CRDs, registrations, dates, disclosures, and
multiple-current-employer records remain visible in
`iapd_manual_review_queue`; they are never silently selected.

Review current quality and operator work:

```bash
python3 -m src.iapd_batch quality \
  --database-url "$PUBLISHER_DATABASE_URL" \
  --bundle-manifest data/iapd/bundles/ia08032026_0/manifest.json
```

The report reads the compact Neon control plane and verified local/R2 manifest;
it no longer depends on detailed person snapshots in Neon. The Operations page
displays feed recovery runs, live job states, and open review reasons. The
Changes page displays conservative firm-level IAPD deltas and filters. Target
Explorer exposes AUM, state, representative count,
freshness, conflict, and representative-disclosure filters. `NULL` enrichment
is displayed as unknown and is never counted as zero.

Required server-side settings are `PUBLISHER_DATABASE_URL` and
`FIRECRAWL_API_KEY`; R2 publication additionally requires the four
`CLOUDFLARE_R2_*` values documented below. Rollback means retaining the prior
local dataset directory and active R2 manifest. No failed run deletes either.

The scheduler reads `deploy/production-refresh.env` first. If that protected
file does not define `PUBLISHER_DATABASE_URL`, it may reuse `DATABASE_URL` and
`FIRECRAWL_API_KEY` from the protected `web/.env.local` file. Both files must
have permission mode `600`; otherwise the job stops before loading secrets.

If the SEC download endpoint is temporarily blocked or you already have the
monthly ZIP and extracted XML, use the manual import path:

```bash
python3 -m src.iapd refresh \
  --database-url "$PUBLISHER_DATABASE_URL" \
  --date 2026-08-04 \
  --source-url "https://reports.adviserinfo.sec.gov/reports/CompilationReports/IA_INDVL_Feed_08_04_2026.xml.zip" \
  --source-zip /path/to/IA_INDVL_Feed_08_04_2026.xml.zip \
  --xml-path /path/to/IA_INDVL_Feed_08_04_2026.xml
```

The same workflow is also available through the CLI as `iapd-refresh` and
`iapd-import`.
