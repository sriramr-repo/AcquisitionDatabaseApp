# SCM RIA Production Runbook

## Operating model

The application uses Bronze, Silver, Gold, Gold V1, reporting exports, and a separate research database. Production is selected explicitly with `SCM_ENV=PROD`; development and tests default to isolated `data-dev` and temporary directories. The production root is the repository's `data/` directory or the explicit `SCM_DATA_DIR` value.

Gold V1 scoring (`SCM_ACQUISITION_V1`) and priority rules are frozen. Operational metadata is stored separately in `pipeline_runs`, `pipeline_stages`, `operational_alerts`, and `backups` tables in `metadata.db`.

## Monthly workflow

The scheduler calls `deploy/production-refresh.sh`, which sets `SCM_ENV=PROD` and invokes `python3 -m src.cli production-refresh`.

1. Discover the latest SEC dataset.
2. Create a persisted run record.
3. Return `NO_CHANGE` when the latest version is already successful.
4. Create a pre-run backup before a new refresh.
5. Download and normalize into an external staging root; validate ZIP, Silver, quality, Gold V1, scoring, exports, change intelligence, research, and reporting gates.
6. Promote versioned tables and artifacts only after all gates pass, then persist stage/run metrics and create change-intelligence and research-refresh outputs.
7. Mark the run `SUCCESS`; failures are persisted and alerted.

Inspect status with:

```bash
SCM_ENV=PROD python3 -m src.cli production-status
SCM_ENV=PROD python3 -m src.cli list-runs
SCM_ENV=PROD python3 -m src.cli show-run RUN_ID
SCM_ENV=PROD python3 -m src.cli production-health-check
```

`NO_CHANGE` is a successful monthly result and does not rebuild dossiers. A new or materially changed target appears in `data/exports/research_refresh/<dataset>/research_refresh_queue.json`.

Discovery provenance is recorded on the `dataset_discovery` stage. `details_json.discovery_source=primary` means the SEC index was read successfully; `discovery_source=fallback` and `fallback_used=true` mean the primary request failed or contained no IA ZIP link. Fallback use remains a successful `NO_CHANGE` when the fallback version is already current, but it increments the run warning count and emits `DISCOVERY_FALLBACK_USED` with severity `WARNING`.

The deployed launchd job is `com.scm.ria.production-refresh`, installed at `~/Library/LaunchAgents/com.scm.ria.production-refresh.plist`. It runs at 06:00 on day 1 of each month and invokes `deploy/production-refresh.sh` with the validated absolute Python interpreter. A host-local advisory lock at `data/.production-refresh.lock` returns `BUSY` for overlapping runs; OS file-lock release handles stale processes. Wrapper logs rotate at 10 MB, retaining one `.1` generation.

## Backups and recovery

Backups are deterministic directories under `data/backups/<backup-id>/` and contain a manifest with SHA-256 hashes for metadata.db, analytics.duckdb, research.db, the active Bronze ZIP, and the Gold V1 Parquet when present.

```bash
SCM_ENV=PROD python3 -m src.cli backup
SCM_ENV=PROD python3 -m src.cli list-backups
SCM_ENV=PROD python3 -m src.cli verify-backup data/backups/BACKUP_ID
SCM_ENV=PROD python3 -m src.cli production-status
SCM_ENV=PROD python3 -m src.cli list-runs
SCM_ENV=PROD python3 -m src.cli show-run RUN_ID
SCM_ENV=PROD python3 -m src.cli research-refresh-queue DATASET_VERSION
SCM_ENV=PROD python3 -m src.cli monthly-report DATASET_VERSION

# Scheduler control
launchctl print gui/$(id -u)/com.scm.ria.production-refresh
launchctl kickstart -k gui/$(id -u)/com.scm.ria.production-refresh
launchctl bootout gui/$(id -u)/com.scm.ria.production-refresh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.scm.ria.production-refresh.plist
```

Restoration is deliberately isolated: `restore_backup()` refuses the active environment and requires an explicit non-production target directory. Verify the isolated copy before any operator-led promotion. Always preserve the current state and make a pre-restore backup before a manual production recovery.

## Failures and alerts

Failures remain visible in `pipeline_runs` with a `FAILED_*` status and are written to `operational_alerts`. The local notifier is intentionally provider-neutral; email/Slack can be added behind `AlertNotifier` without changing pipeline code. Do not retry a failed refresh with `--force` until the failed run and its backup have been inspected.

Typical checks:

- `FAILED_DOWNLOAD` / `FAILED_VALIDATION`: inspect SEC response, ZIP validation, and the pre-run backup.
- `FAILED_SILVER` / `FAILED_GOLD`: do not promote; inspect stage details and schema drift.
- `FAILED_EXPORT` / `FAILED_REPORTING`: preserve the successfully built data and rerun the export/report stage only after diagnosis.
- `FAILED_BACKUP`: stop; no new dataset should be promoted without a valid pre-run backup.

## Reports and change intelligence

JSON reports are under `data/exports/reports/`. Target exports are under `data/exports/targets/`. Monthly change intelligence identifies new/removed firms, priority transitions, target-band entries/exits, material AUM and staffing changes, regulatory disclosure changes, and score/priority changes without changing scoring formulas.

## Research refresh

Research is separate from Gold. The queue emits `NEW_TARGET_RESEARCH`, `REFRESH_REQUIRED`, `REGULATORY_REVIEW_REQUIRED`, `PRIORITY_CHANGE_REVIEW`, and `NO_REFRESH_REQUIRED`. Stable firms are not automatically re-researched. Existing analyst evidence and dossiers must not be deleted or overwritten by automation.

## Rollback and data recovery

Keep the previous successful dataset, versioned DuckDB tables, archive ZIP, Parquet, metadata, and research database. For corruption, stop scheduled execution, verify the latest backup, restore into an isolated directory, validate hashes and row counts, then perform a controlled operator-approved promotion. Never use broad deletion or overwrite the active production root as an exploratory recovery step.

## Score and schema management

Record the dataset version, source checksum, code version, score version, configuration version, and schema version in each run. A schema drift report is a release gate for new data. A score-version change requires a separate business approval and a new release identifier; it is not part of routine monthly operations.

## Operator responsibilities

Review the monthly run status, backup validity, quality and row-count invariants, change-intelligence events, research refresh queue, and alerts. Confirm that the scheduler is loaded and that disk space is sufficient. Keep the Python environment aligned with `requirements.lock`.

## First live new-dataset checklist

After the first scheduled run that discovers a version newer than the current dataset, verify the run with `show-run RUN_ID`: discovery source, backup ID, stage timings, `SUCCESS` status, Silver/Gold V1 row counts, and priority counts. Then verify the new Bronze ZIP, versioned Silver and Gold V1 tables, Parquet, target exports, monthly report, change-intelligence file, research-refresh queue, and the prior version's retained tables/artifacts. Confirm the current registry points to the new version and that Priority A/research changes are reviewed. Verify the linked backup before closing the run.

## Monthly verification commands

```bash
launchctl print gui/$(id -u)/com.scm.ria.production-refresh
SCM_ENV=PROD SCM_DATA_DIR=/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data python3 -m src.cli list-runs --limit 5
SCM_ENV=PROD SCM_DATA_DIR=/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data python3 -m src.cli show-run RUN_ID
SCM_ENV=PROD SCM_DATA_DIR=/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data python3 -m src.cli production-status
SCM_ENV=PROD SCM_DATA_DIR=/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data python3 -m src.cli production-health-check
SCM_ENV=PROD SCM_DATA_DIR=/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data python3 -m src.cli list-backups
SCM_ENV=PROD SCM_DATA_DIR=/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data python3 -m src.cli verify-backup data/backups/BACKUP_ID
tail -100 /Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/logs/launchd.out.log
tail -100 /Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/logs/launchd.err.log
```
