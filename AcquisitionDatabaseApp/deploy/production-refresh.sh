#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_ROOT"
REFRESH_ENV_FILE="${SCM_REFRESH_ENV_FILE:-$APP_ROOT/deploy/production-refresh.env}"
if [ -f "$REFRESH_ENV_FILE" ]; then
  FILE_MODE="$(stat -f '%Lp' "$REFRESH_ENV_FILE")"
  if (( (8#$FILE_MODE & 8#077) != 0 )); then
    printf '%s\n' "Refusing to load $REFRESH_ENV_FILE: permissions must be 600." >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090 -- operator-controlled, permission-checked secrets file
  source "$REFRESH_ENV_FILE"
  set +a
fi
WEB_ENV_FILE="$APP_ROOT/web/.env.local"
if [ -z "${PUBLISHER_DATABASE_URL:-}" ] && [ -f "$WEB_ENV_FILE" ]; then
  WEB_FILE_MODE="$(stat -f '%Lp' "$WEB_ENV_FILE")"
  if (( (8#$WEB_FILE_MODE & 8#077) != 0 )); then
    printf '%s\n' "Refusing to load $WEB_ENV_FILE: permissions must be 600." >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090 -- local dashboard secrets are permission-checked.
  source "$WEB_ENV_FILE"
  set +a
fi
export SCM_ENV=PROD
export SCM_DATA_DIR="$APP_ROOT/data"
PYTHON_BIN="${SCM_PYTHON:-$(command -v python3)}"
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
PUBLISHER_DATABASE_URL="${PUBLISHER_DATABASE_URL:-${DATABASE_URL:-postgres://scm:scm@localhost:5432/scm_dashboard}}"
REFRESH_OUTPUT="$("$PYTHON_BIN" -m src.cli production-refresh)"
printf '%s\n' "$REFRESH_OUTPUT"
DATASET_VERSION="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["dataset_version"])' <<< "$REFRESH_OUTPUT")"
"$PYTHON_BIN" -m src.dashboard_publisher publish \
  --dataset-version "$DATASET_VERSION" \
  --database-url "$PUBLISHER_DATABASE_URL"
ADV_ZIP="$APP_ROOT/data/bronze/raw/${DATASET_VERSION}.zip"
if [ ! -f "$ADV_ZIP" ]; then
  ADV_ZIP="$APP_ROOT/data/bronze/raw/${DATASET_VERSION}_0.zip"
fi
if [ -f "$ADV_ZIP" ]; then
  "$PYTHON_BIN" -m src.adv_facts publish \
    --zip-path "$ADV_ZIP" \
    --dataset-version "$DATASET_VERSION" \
    --database-url "$PUBLISHER_DATABASE_URL"
  "$PYTHON_BIN" -m src.adv_ocr process-queue \
    --database-url "$PUBLISHER_DATABASE_URL" \
    --limit "${ADV_OCR_BATCH_SIZE:-10}"
else
  printf '%s\n' "Form ADV publication skipped: no validated SEC IA ZIP exists for $DATASET_VERSION."
fi
IAPD_OUTPUT="$("$PYTHON_BIN" -m src.iapd_recovery \
  --database-url "$PUBLISHER_DATABASE_URL" --latest-feed)"
printf '%s\n' "$IAPD_OUTPUT"
IAPD_STATUS="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["status"])' <<< "$IAPD_OUTPUT")"
if [ "$IAPD_STATUS" = "success" ] || [ "$IAPD_STATUS" = "fallback_success" ]; then
  IAPD_ZIP="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["source_zip"])' <<< "$IAPD_OUTPUT")"
  IAPD_URL="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["source_url"])' <<< "$IAPD_OUTPUT")"
  IAPD_DATE="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["snapshot_date"])' <<< "$IAPD_OUTPUT")"
  FIRM_TABLE="gold_scm_acquisition_v1_${DATASET_VERSION}"
  "$PYTHON_BIN" -m src.iapd_local build-store \
    --source-zip "$IAPD_ZIP" \
    --source-url "$IAPD_URL" \
    --snapshot-date "$IAPD_DATE" \
    --dataset-version "$DATASET_VERSION" \
    --output-root "$APP_ROOT/data/iapd/local" \
    --firm-source-duckdb "$APP_ROOT/data/analytics.duckdb" \
    --firm-table "$FIRM_TABLE"
  mkdir -p "$APP_ROOT/data/iapd/local/changes"
  PREVIOUS_IAPD_DB="$APP_ROOT/data/iapd/local/datasets/$DATASET_VERSION.previous/iapd.duckdb"
  IAPD_COMPARE_ARGS=(
    --current-database "$APP_ROOT/data/iapd/local/datasets/$DATASET_VERSION/iapd.duckdb"
    --report-path "$APP_ROOT/data/iapd/local/changes/${DATASET_VERSION}_${IAPD_DATE}.json"
  )
  if [ -f "$PREVIOUS_IAPD_DB" ]; then
    IAPD_COMPARE_ARGS+=(--previous-database "$PREVIOUS_IAPD_DB")
  fi
  IAPD_CHANGE_REPORT="$APP_ROOT/data/iapd/local/changes/${DATASET_VERSION}_${IAPD_DATE}.json"
  "$PYTHON_BIN" -m src.iapd_local compare-snapshots "${IAPD_COMPARE_ARGS[@]}"
  "$PYTHON_BIN" -m src.iapd_change_publisher publish \
    --report-path "$IAPD_CHANGE_REPORT" \
    --database-url "$PUBLISHER_DATABASE_URL"
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
    "$PYTHON_BIN" -m src.iapd_local publish-r2 \
      --manifest "$APP_ROOT/data/iapd/bundles/$DATASET_VERSION/manifest.json" \
      --report-path "$APP_ROOT/data/iapd/r2-publications/$DATASET_VERSION.json"
  else
    printf '%s\n' "Cloudflare R2 publication skipped: required server-side credentials are not configured."
  fi
  IAPD_LIVE_LIMIT="${IAPD_LIVE_BATCH_SIZE:-25}"
  if [ "$IAPD_LIVE_LIMIT" -gt 0 ]; then
    "$PYTHON_BIN" -m src.iapd_batch run \
      --database-url "$PUBLISHER_DATABASE_URL" \
      --local-database "$APP_ROOT/data/iapd/local/datasets/$DATASET_VERSION/iapd.duckdb" \
      --limit "$IAPD_LIVE_LIMIT" \
      --workers "${IAPD_LIVE_WORKERS:-2}" \
      --freshness-days "${IAPD_LIVE_FRESHNESS_DAYS:-30}"
  fi
fi
