# SCM RIA Intelligence V1.0 Deployment Report

## Status

`SCM_RIA_INTELLIGENCE_V1.0 DEPLOYED — MONTHLY PRODUCTION OPERATION ENABLED`

Deployment date: 2026-08-17

## Release and runtime

- Release: `SCM_RIA_INTELLIGENCE_V1.0`
- Dataset: `ia07012026`
- Git code version recorded by the application: `5b32da66b7148c0f3adfa08628a2164a1710c075`
- Score version: `SCM_ACQUISITION_V1`
- Python: `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3` (3.14.6)
- Pinned dependencies: `requirements.lock`; installed versions matched the lock during validation.
- The worktree contains pre-existing uncommitted changes. They were not reverted or silently committed; the validated deployment scope is the production-readiness implementation and its tests.

## PROD paths

- Root: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data`
- Bronze: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/bronze`
- Silver: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/silver`
- Gold: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/gold`
- Archive: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/archive`
- Exports: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/exports`
- Logs: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/logs`
- Metadata: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/metadata.db`
- Analytics: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/analytics.duckdb`
- Research: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/research.db`
- Backups: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data/backups`

## Acceptance evidence

- Production health check: passed.
- Pre-activation backup: `backup-20260817T192226Z-c9068e5e`; five protected files; hash verification passed.
- Manual production run: `275c2b68019949cca1150f4c23e5cd9b`; `NO_CHANGE`; zero errors.
- Scheduler smoke-test run: `b4f00257f6ce42b598b6fb97603363c7`; `NO_CHANGE`; launchd exit code 0.
- Clean-room acceptance: success path and eight controlled failure cases passed.
- Full regression: 162 tests passed; existing deprecation warnings remain non-blocking.

## Scheduler

- Label: `com.scm.ria.production-refresh`
- Plist: `/Users/sriramramanan/Library/LaunchAgents/com.scm.ria.production-refresh.plist`
- Command: `/bin/bash /Users/sriramramanan/GitHub/AcquisitionDatabaseApp/deploy/production-refresh.sh`
- Python: `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`
- Cadence: 06:00 on the first day of every month.
- Logs: `data/logs/launchd.out.log` and `data/logs/launchd.err.log`.
- Persistence: user LaunchAgent bootstrapped in `gui/$(id -u)`; static persistence semantics validated without reboot.
- Concurrency: `data/.production-refresh.lock`; overlapping invocation returns `BUSY`.

## Protected production invariants

- Silver: 16,935 rows
- Legacy Gold: 16,935 rows
- Gold V1: 16,935 rows
- Priorities: EXCLUDED 16,142; PRIORITY_A 49; PRIORITY_B 512; PRIORITY_C 232
- Priority A research: 49 `RESEARCH_COMPLETE`
- Bronze SHA-256: `f7b9636b8011611289802a6b581688f32f09176c7307760a1a33e64f161ad98d`
- Gold V1 Parquet SHA-256: `35719e8f573296b41548d09bd53e409c94fa32e2c97c6bce3f157bdc68a7fd`

## Operator reference

```bash
export SCM_ENV=PROD
export SCM_DATA_DIR=/Users/sriramramanan/GitHub/AcquisitionDatabaseApp/data
python3 -m src.cli production-health-check
python3 -m src.cli production-status
python3 -m src.cli production-refresh
python3 -m src.cli list-runs
python3 -m src.cli show-run RUN_ID
python3 -m src.cli backup
python3 -m src.cli list-backups
python3 -m src.cli verify-backup data/backups/BACKUP_ID
python3 -m src.cli research-refresh-queue DATASET_VERSION
python3 -m src.cli monthly-report DATASET_VERSION
launchctl bootout gui/$(id -u)/com.scm.ria.production-refresh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.scm.ria.production-refresh.plist
```

## Limitations and rollback

SEC discovery returned an HTTP/network failure during smoke tests, so the validated fallback correctly produced `NO_CHANGE`; no live new dataset was promoted. Existing deprecation warnings are recorded but are not runtime blockers. For recovery, stop the LaunchAgent, verify the latest backup, restore into an isolated directory, and perform an explicit validated promotion; active-path overwrite is refused by the restore utility.
