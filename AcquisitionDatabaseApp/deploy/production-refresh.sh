#!/usr/bin/env bash
set -euo pipefail
CURRENT_STAGE=configuration
trap 'printf "Refresh failed at stage: %s; dependent stages were not run.\n" "$CURRENT_STAGE" >&2' ERR

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_ROOT"
if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != "--dry-run" ] && [ "$1" != "--print-target-fingerprint" ]; }; then
  printf '%s\n' 'Usage: production-refresh.sh [--dry-run|--print-target-fingerprint]' >&2
  exit 2
fi
REFRESH_ENV_FILE="${SCM_REFRESH_ENV_FILE:-$APP_ROOT/deploy/production-refresh.env}"
if [ ! -f "$REFRESH_ENV_FILE" ]; then
  printf '%s\n' "Production refresh environment file not found: $REFRESH_ENV_FILE" >&2
  exit 1
fi
FILE_MODE="$(stat -f '%Lp' "$REFRESH_ENV_FILE")"
if (( (8#$FILE_MODE & 8#077) != 0 )); then
  printf '%s\n' "Refusing to load $REFRESH_ENV_FILE: permissions must be 600." >&2
  exit 1
fi
unset DATABASE_URL PUBLISHER_DATABASE_URL SCM_PRODUCTION_DATABASE_FINGERPRINT IAPD_FIRM_ACTIVATION_MANIFEST
set -a
# shellcheck disable=SC1090 -- operator-controlled, permission-checked secrets file
source "$REFRESH_ENV_FILE"
set +a
: "${DATABASE_URL:?DATABASE_URL must be set in $REFRESH_ENV_FILE}"
: "${PUBLISHER_DATABASE_URL:?PUBLISHER_DATABASE_URL must be set in $REFRESH_ENV_FILE}"
export SCM_ENV=PROD
export SCM_DATA_DIR="$APP_ROOT/data"
PYTHON_BIN="${SCM_PYTHON:-$(command -v python3)}"
if [ "${1:-}" = "--print-target-fingerprint" ]; then
  exec "$PYTHON_BIN" -m src.refresh_preflight --print-target-fingerprint
fi
: "${SCM_PRODUCTION_DATABASE_FINGERPRINT:?SCM_PRODUCTION_DATABASE_FINGERPRINT must be set in $REFRESH_ENV_FILE}"
if [ "${1:-}" = "--dry-run" ]; then
  exec "$PYTHON_BIN" -m src.refresh_preflight --dry-run
fi
CURRENT_STAGE=preflight
"$PYTHON_BIN" -m src.refresh_preflight
LOG_DIR="$APP_ROOT/data/logs"
rotate_log() {
  local path="$1"
  if [ -f "$path" ] && [ "$(wc -c < "$path")" -ge 10485760 ]; then
    mv -f "$path" "$path.1"
  fi
}
mkdir -p "$LOG_DIR"
rotate_log "$LOG_DIR/launchd.out.log"
rotate_log "$LOG_DIR/launchd.err.log"
CURRENT_STAGE=sec_refresh
PRODUCTION_REFRESH_ARGS=(-m src.cli production-refresh)
if [ -n "${IAPD_FIRM_ACTIVATION_MANIFEST:-}" ]; then
  PRODUCTION_REFRESH_ARGS+=(--firm-activation-manifest "$IAPD_FIRM_ACTIVATION_MANIFEST")
fi
REFRESH_OUTPUT="$("$PYTHON_BIN" "${PRODUCTION_REFRESH_ARGS[@]}")"
printf '%s\n' "$REFRESH_OUTPUT"
DATASET_VERSION="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["dataset_version"])' <<< "$REFRESH_OUTPUT")"
"$PYTHON_BIN" -c 'import json,sys; r=json.loads(sys.stdin.read()); sys.exit(0 if r.get("status") in ("SUCCESS","NO_CHANGE","success","skipped") and r.get("dataset_version") else 1)' <<< "$REFRESH_OUTPUT"
CURRENT_STAGE=dashboard_publication
"$PYTHON_BIN" -m src.dashboard_publisher publish \
  --dataset-version "$DATASET_VERSION" \
  --database-url "$PUBLISHER_DATABASE_URL"
ADV_ZIP="$APP_ROOT/data/bronze/raw/${DATASET_VERSION}.zip"
if [ ! -f "$ADV_ZIP" ]; then
  ADV_ZIP="$APP_ROOT/data/bronze/raw/${DATASET_VERSION}_0.zip"
fi
if [ -f "$ADV_ZIP" ] && "$PYTHON_BIN" -c '
import sys, zipfile
try:
    with zipfile.ZipFile(sys.argv[1]) as archive:
        valid = any(name.lower().endswith(".csv") for name in archive.namelist())
except (OSError, zipfile.BadZipFile):
    valid = False
raise SystemExit(0 if valid else 1)
' "$ADV_ZIP"; then
  CURRENT_STAGE=adv_publication
  "$PYTHON_BIN" -m src.adv_facts publish \
    --zip-path "$ADV_ZIP" \
    --dataset-version "$DATASET_VERSION" \
    --database-url "$PUBLISHER_DATABASE_URL"
  "$PYTHON_BIN" -m src.adv_ocr process-queue \
    --database-url "$PUBLISHER_DATABASE_URL" \
    --limit "${ADV_OCR_BATCH_SIZE:-10}"
else
  printf '%s\n' "Form ADV publication skipped: no validated SEC IA CSV ZIP exists for $DATASET_VERSION."
fi
CURRENT_STAGE=iapd_discovery_import
IAPD_OUTPUT="$("$PYTHON_BIN" -m src.iapd_recovery \
  --database-url "$PUBLISHER_DATABASE_URL" --latest-feed)"
printf '%s\n' "$IAPD_OUTPUT"
IAPD_STATUS="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["status"])' <<< "$IAPD_OUTPUT")"
if [ "$IAPD_STATUS" = "success" ] || [ "$IAPD_STATUS" = "fallback_success" ]; then
  IAPD_ZIP="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["source_zip"])' <<< "$IAPD_OUTPUT")"
  IAPD_URL="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["source_url"])' <<< "$IAPD_OUTPUT")"
  IAPD_DATE="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["snapshot_date"])' <<< "$IAPD_OUTPUT")"
  FIRM_TABLE="gold_scm_acquisition_v1_${DATASET_VERSION}"
  CURRENT_STAGE=iapd_local_store
  "$PYTHON_BIN" -m src.iapd_local build-store \
    --source-zip "$IAPD_ZIP" \
    --source-url "$IAPD_URL" \
    --snapshot-date "$IAPD_DATE" \
    --dataset-version "$DATASET_VERSION" \
    --output-root "$APP_ROOT/data/iapd/local" \
    --firm-source-duckdb "$APP_ROOT/data/analytics.duckdb" \
    --firm-table "$FIRM_TABLE"
  mkdir -p "$APP_ROOT/data/iapd/local/changes"
  PREVIOUS_IAPD_DB="$("$PYTHON_BIN" -c 'from pathlib import Path; import sys; from src.iapd_local import previous_distinct_snapshot; print(previous_distinct_snapshot(Path(sys.argv[1])) or "")' "$APP_ROOT/data/iapd/local/datasets/$DATASET_VERSION/iapd.duckdb")"
  IAPD_COMPARE_ARGS=(
    --current-database "$APP_ROOT/data/iapd/local/datasets/$DATASET_VERSION/iapd.duckdb"
    --report-path "$APP_ROOT/data/iapd/local/changes/${DATASET_VERSION}_${IAPD_DATE}.json"
  )
  if [ -f "$PREVIOUS_IAPD_DB" ]; then
    IAPD_COMPARE_ARGS+=(--previous-database "$PREVIOUS_IAPD_DB")
  fi
  IAPD_CHANGE_REPORT="$APP_ROOT/data/iapd/local/changes/${DATASET_VERSION}_${IAPD_DATE}.json"
  CURRENT_STAGE=iapd_comparison
  "$PYTHON_BIN" -m src.iapd_local compare-snapshots "${IAPD_COMPARE_ARGS[@]}"
  CURRENT_STAGE=iapd_compact_publication
  "$PYTHON_BIN" -m src.iapd_change_publisher publish \
    --report-path "$IAPD_CHANGE_REPORT" \
    --database-url "$PUBLISHER_DATABASE_URL"
  CURRENT_STAGE=iapd_bundles
  "$PYTHON_BIN" -m src.iapd_local build-bundles \
    --dataset-version "$DATASET_VERSION" \
    --local-root "$APP_ROOT/data/iapd/local" \
    --output-root "$APP_ROOT/data/iapd/bundles" \
    --firm-source-duckdb "$APP_ROOT/data/analytics.duckdb" \
    --firm-table "$FIRM_TABLE"
  if [ -n "${CLOUDFLARE_R2_ACCOUNT_ID:-}" ] && \
     [ -n "${CLOUDFLARE_R2_ACCESS_KEY_ID:-}" ] && \
     [ -n "${CLOUDFLARE_R2_SECRET_ACCESS_KEY:-}" ] && \
     [ -n "${CLOUDFLARE_R2_BUCKET:-}" ]; then
    mkdir -p "$APP_ROOT/data/iapd/r2-publications"
    CURRENT_STAGE=iapd_r2_publication
    "$PYTHON_BIN" -m src.iapd_local publish-r2 \
      --manifest "$APP_ROOT/data/iapd/bundles/$DATASET_VERSION/manifest.json" \
      --report-path "$APP_ROOT/data/iapd/r2-publications/$DATASET_VERSION.json"
  else
    printf '%s\n' "INCOMPLETE: Cloudflare R2 publication skipped; required credentials are missing." >&2
    exit 1
  fi
  IAPD_LIVE_LIMIT="${IAPD_LIVE_BATCH_SIZE:-25}"
  if [ "$IAPD_LIVE_LIMIT" -gt 0 ]; then
    CURRENT_STAGE=iapd_live_batch
    IAPD_LIVE_OUTPUT="$("$PYTHON_BIN" -m src.iapd_batch run \
      --database-url "$PUBLISHER_DATABASE_URL" \
      --local-database "$APP_ROOT/data/iapd/local/datasets/$DATASET_VERSION/iapd.duckdb" \
      --limit "$IAPD_LIVE_LIMIT" \
      --workers "${IAPD_LIVE_WORKERS:-1}" \
      --freshness-days "${IAPD_LIVE_FRESHNESS_DAYS:-30}")"
    printf '%s\n' "$IAPD_LIVE_OUTPUT"
    "$PYTHON_BIN" -c 'import json,sys; r=json.loads(sys.stdin.read()); sys.exit(0 if r.get("status") == "success" else 1)' <<< "$IAPD_LIVE_OUTPUT"
  else
    printf '%s\n' 'IAPD live batch explicitly skipped: configured limit is zero.'
  fi
else
  printf '%s\n' "INCOMPLETE: IAPD discovery/import failed; comparison and R2 stages were not run." >&2
  exit 1
fi
printf '%s\n' 'Production refresh stages completed.'
