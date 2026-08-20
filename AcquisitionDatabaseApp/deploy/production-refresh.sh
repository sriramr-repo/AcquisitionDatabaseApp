#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_ROOT"
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
PUBLISHER_DATABASE_URL="\${PUBLISHER_DATABASE_URL:-postgres://scm:scm@localhost:5432/scm_dashboard}"
REFRESH_OUTPUT="$("$PYTHON_BIN" -m src.cli production-refresh)"
printf '%s\n' "$REFRESH_OUTPUT"
DATASET_VERSION="$("$PYTHON_BIN" -c 'import json,sys; print(json.loads(sys.stdin.read())["dataset_version"])' <<< "$REFRESH_OUTPUT")"
"$PYTHON_BIN" -m src.dashboard_publisher publish \
  --dataset-version "$DATASET_VERSION" \
  --database-url "$PUBLISHER_DATABASE_URL"
