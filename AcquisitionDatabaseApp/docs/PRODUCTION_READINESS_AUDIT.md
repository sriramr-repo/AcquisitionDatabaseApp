# Production Readiness Audit and Release Baseline

Baseline captured 2026-08-16 before operational hardening.

## Baseline

- Repository: `/Users/sriramramanan/GitHub/AcquisitionDatabaseApp`
- Branch: `main`
- Code commit: `5b32da66b7148c0f3adfa08628a2164a1710c075`
- Dataset: `ia07012026`
- Score version: `SCM_ACQUISITION_V1`
- Silver: 16,935 rows / 16,935 distinct firms
- Legacy Gold: 16,935 rows / 16,935 distinct firms
- Gold V1: 16,935 rows / 16,935 distinct firms
- Priority counts: EXCLUDED 16,142; PRIORITY_A 49; PRIORITY_B 512; PRIORITY_C 232
- Bronze SHA-256: `f7b9636b8011611289802a6b581688f32f09176c7307760a1a33e64f161ad98d`
- Gold V1 Parquet SHA-256: `35719e8f573296b41548d09bdad53e409c94fa32e2c97c6bce3f157bdc68a7fd`
- Research: 49 `RESEARCH_COMPLETE`, 139 sources, Priority B/C untouched
- Regression baseline: 72 passing tests and 13 existing warnings

## Findings

### Entry points

`src.cli` exposes ingestion, refresh, dataset, dashboard, health, production status/refresh, run, backup, restore-verification, and research-queue commands. `src.pipeline.run_pipeline` is the existing ingestion path. `deploy/production-refresh.sh` is the scheduler entry point.

### Mutable state

Production state includes Bronze ZIP/extracted files, versioned DuckDB tables and Parquet, `metadata.db`, `research.db`, reports, dossiers, logs, and profiling/change artifacts. The new backup layer records hashes for the critical database, Bronze, and Gold files.

### Risks found and addressed

- Relative `data/` paths: replaced by repository-rooted, explicit `SCM_ENV`/`SCM_DATA_DIR` resolution.
- Import-time registry path staleness: metadata registry now follows the active settings path.
- No operational run registry: added separate run/stage/alert tables.
- No verified recovery workflow: added manifest/hash backups and isolated restore refusal for active paths.
- No production CLI/scheduler boundary: added production commands and launchd wrapper.
- No business-facing refresh queue: added event-driven change and research queue modules.
- CLI test compatibility: exposed a Click command object for current Typer/Click versions.

### Clean-room acceptance result

The production refresh entry point now stages a new dataset in an external temporary root, validates ZIP/Silver/quality/Gold V1/scoring/exports/change intelligence/research/reporting gates, and promotes only after all gates pass. A deterministic second-dataset fixture passed the success path, retained the baseline and previous versions, and produced the expected change-intelligence and research-queue artifacts. Controlled failures at download, ZIP validation, Silver, quality, Gold, export, reporting, and promotion all failed closed with the baseline remaining current. Backup verification and isolated restore also passed.

The legacy pipeline remains available for explicit compatibility injection and is not the default production refresh runner.

## Environment policy

`DEV` defaults to `<repo>/data-dev`, `TEST` should use a temporary `SCM_DATA_DIR`, and `PROD` uses `<repo>/data` unless `SCM_DATA_DIR` is explicitly set. Production commands refuse to run unless `SCM_ENV=PROD`.
