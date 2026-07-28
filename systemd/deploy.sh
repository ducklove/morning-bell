#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/cantabile/Works/morning-bell"
LOCK_FILE="/tmp/polymarket-briefing-deploy.lock"
LOG_FILE="$REPO_DIR/state/deploy.log"

mkdir -p "$REPO_DIR/state"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

cd "$REPO_DIR"

# Don't swap code out from under a live briefing run.
if systemctl --user is-active --quiet polymarket-briefing.service; then
  echo "$(date -Iseconds) briefing service is running, skipping deploy" >> "$LOG_FILE"
  exit 0
fi

git fetch origin main --quiet
LOCAL_REV="$(git rev-parse HEAD)"
REMOTE_REV="$(git rev-parse origin/main)"

if [ "$LOCAL_REV" = "$REMOTE_REV" ]; then
  exit 0
fi

git reset --hard origin/main --quiet
.venv/bin/pip install -e . --quiet
echo "$(date -Iseconds) deployed ${LOCAL_REV:0:7} -> ${REMOTE_REV:0:7}" >> "$LOG_FILE"
