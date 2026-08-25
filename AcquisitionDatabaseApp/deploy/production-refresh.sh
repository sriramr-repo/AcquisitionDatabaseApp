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
PUBLISHER_DATABASE_URL="${PUBLISHER_DATABASE_URL:-postgres://scm:scm@localhost:5432/scm_dashboard}"
REFRESH_OUTPUT="$("$PYTHON_BIN" -m src.cli production-refresh)"
printf '%s\n' "$REFRESH_OUTPUT"
DATASET_VERSION="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["dataset_version"])' <<< "$REFRESH_OUTPUT")"
"$PYTHON_BIN" -m src.dashboard_publisher publish \
  --dataset-version "$DATASET_VERSION" \
  --database-url "$PUBLISHER_DATABASE_URL"
IAPD_OUTPUT="$("$PYTHON_BIN" -m src.iapd refresh \
  --database-url "$PUBLISHER_DATABASE_URL")"
printf '%s\n' "$IAPD_OUTPUT"
IAPD_STATUS="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["status"])' <<< "$IAPD_OUTPUT")"
if [ "$IAPD_STATUS" = "success" ]; then
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
fi
