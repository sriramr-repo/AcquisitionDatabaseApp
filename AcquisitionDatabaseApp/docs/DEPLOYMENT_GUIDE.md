# Deployment Guide

## Supported host

The initial deployment target is the current controlled macOS/Unix host. The same commands work on Linux with a systemd timer or cron replacing the launchd template.

## Requirements and setup

- Python 3.12 or newer
- Local filesystem with write access to the application data root
- Network access to the SEC source for monthly refresh
- Sufficient disk space for current data, archives, backups, and historical DuckDB tables

```bash
cd /absolute/path/to/AcquisitionDatabaseApp
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.lock
```

The application has three explicit environment modes: `DEV`, `TEST`, and `PROD`. Set `SCM_ENV` and, when needed, `SCM_DATA_DIR`; otherwise development uses a repository-rooted `data-dev` directory and production uses the repository-rooted `data/` directory.

## Filesystem layout

`bronze/` stores downloaded SEC ZIPs and extracted source files; `silver/` and `gold/` store versioned analytical outputs; `archive/` preserves historical source material; `exports/` stores reports, target exports, dossiers, and queues; `backups/` stores verified backup directories; `run_manifests/` stores reproducibility manifests; `metadata.db`, `analytics.duckdb`, and `research.db` store registries and analytical/research state.

## Initialize and verify

```bash
export SCM_ENV=PROD
export SCM_DATA_DIR=/absolute/path/to/AcquisitionDatabaseApp/data
python3 -m src.cli production-status
python3 -m src.cli production-health-check
python3 -m src.cli backup
```

The first controlled run should be `NO_CHANGE` if the current dataset is already registered. Verify the backup with `verify-backup` before installing the scheduler.

## Scheduler installation on macOS

Copy `deploy/launchd/com.scm.ria.production-refresh.plist.template`, replace the two absolute paths, and install it as `~/Library/LaunchAgents/com.scm.ria.production-refresh.plist`. Then load it with `launchctl bootstrap gui/$(id -u) <plist>`. Check output in `data/logs/launchd.out.log` and `launchd.err.log`.

On Linux, call `deploy/production-refresh.sh` from a systemd timer or cron entry with an explicit working directory and `SCM_ENV=PROD`.

## Rollback

Stop the scheduler, inspect `list-runs`, identify the last successful backup, verify it, restore to an isolated directory, and validate the restored files. Production promotion is an explicit operator action after the isolated validation; the built-in restore function refuses to overwrite the active environment.

## Health and ongoing operation

Run `production-health-check` after deployment and after every recovery. Retain run manifests and backups according to local retention policy. Do not commit secrets, `.env` files, database copies, logs, or backup contents.
