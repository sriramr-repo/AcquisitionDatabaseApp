# IAPD representative enrichment

The monthly SEC IAPD compilation report is the dashboard's person-level
enrichment source. It is a snapshot feed, not a live IAPD API substitute.

On the fourth day of each month, the production wrapper requests:

```text
https://reports.adviserinfo.sec.gov/reports/CompilationReports/IA_INDVL_Feed_MM_DD_YYYY.xml.zip
```

The job retains the validated ZIP and extracted XML under `data/iapd/raw/`,
records its source URL and SHA-256 hash, and imports it into the hosted
PostgreSQL IAPD tables. A duplicate snapshot date or file hash is skipped.

The import captures individual CRD and names, current employer firm CRD/name,
business and branch addresses supplied by the feed, current and prior
registration details, employment history, other businesses, and the feed's
disclosure flags. Current employer firm CRD is the only firm-link key; no
person-level value overwrites the SEC firm master, Silver, Gold, or research
records.

Each import is auditable through `iapd_individual_snapshots` and compared with
the preceding successful snapshot. The change table records new/disappeared
individuals, employer changes, registration-status changes, employment-history
changes, and newly reported disclosure flags. Parse anomalies are retained in
`iapd_import_issues`; missing CRDs, missing names, duplicate people, malformed
XML, empty ZIPs, and unexpected file contents are never silently accepted.

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
