#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO_DIR="${BRIEFING_REPO_DIR:-$HOME/Works/morning-bell}"
STATE_DIR="${POLYMARKET_BRIEFING_STATE_DIR:-$HOME/.local/state/morning-bell}"
RELEASES_DIR="${BRIEFING_RELEASES_DIR:-$HOME/.local/share/morning-bell/releases}"
mkdir -p "$STATE_DIR" "$RELEASES_DIR"
export POLYMARKET_BRIEFING_STATE_DIR="$STATE_DIR"
exec 9>"$STATE_DIR/run.lock"
flock -n 9 || exit 0
exec >>"$STATE_DIR/deploy.log" 2>&1

cd "$REPO_DIR"
# Also protect the first upgrade from an older service without the shared lock.
if systemctl --user is-active --quiet polymarket-briefing.service; then
  echo "$(date -Iseconds) briefing is active; skipping deployment"
  exit 0
fi
git diff --quiet && git diff --cached --quiet || {
  echo "Tracked local changes exist; deployment stopped"
  exit 1
}

fetch_ok=false
for attempt in 1 2 3; do
  if timeout 60s git fetch origin main --quiet; then
    fetch_ok=true
    break
  fi
  sleep "$((attempt * 2))"
done
"$fetch_ok" || exit 1

LOCAL_REV="$(git rev-parse HEAD)"
REMOTE_REV="$(git rev-parse origin/main)"
if [ "$LOCAL_REV" = "$REMOTE_REV" ] && [ -f "$STATE_DIR/deployed-revision" ] &&
   [ "$(cat "$STATE_DIR/deployed-revision")" = "$REMOTE_REV" ]; then
  exit 0
fi

STAMP="$(date +%Y%m%dT%H%M%S)-$$"
RELEASE="$RELEASES_DIR/$REMOTE_REV-$STAMP"
mkdir "$RELEASE"
git archive "$REMOTE_REV" | tar -x -C "$RELEASE"
"${BRIEFING_PYTHON:-python3}" -m venv "$RELEASE/venv"
"$RELEASE/venv/bin/pip" install "$RELEASE[dev]" --quiet --timeout 20 --retries 3
(
  cd "$RELEASE"
  venv/bin/ruff check .
  venv/bin/pytest -q
  bash -n systemd/deploy.sh
  bash -n systemd/prune-releases.sh
)
"$RELEASE/venv/bin/polymarket-briefing" validate-config --config "$REPO_DIR/config.yaml"
"$RELEASE/venv/bin/python" - "$REPO_DIR" <<'PY'
import sys
from pathlib import Path
from polymarket_briefing.config import load_config
from polymarket_briefing.storage import resolve_storage_path
repo = Path(sys.argv[1]).resolve()
path = resolve_storage_path(load_config(repo / "config.yaml").storage.path).resolve()
if path.is_relative_to(repo):
    raise SystemExit("Move the configured state DB outside the checkout before deploying")
PY
# Copy legacy state with SQLite backup, leaving the original intact.
"$RELEASE/venv/bin/polymarket-briefing" backup-state \
  --config "$REPO_DIR/config.yaml" --output "$STATE_DIR/backups/$STAMP.sqlite"

UNIT_DIR="$HOME/.config/systemd/user"
UNIT_BACKUP="$STATE_DIR/unit-backups/$STAMP"
mkdir -p "$UNIT_DIR" "$UNIT_BACKUP"
for unit in "$RELEASE"/systemd/*.service "$RELEASE"/systemd/*.timer; do
  name="$(basename "$unit")"
  if [ -f "$UNIT_DIR/$name" ]; then cp "$UNIT_DIR/$name" "$UNIT_BACKUP/$name"; fi
done

if [ -L "$REPO_DIR/.venv" ]; then
  PREVIOUS_VENV="$(readlink -f "$REPO_DIR/.venv")"
else
  PREVIOUS_VENV="$REPO_DIR/.venv-before-$STAMP"
  mv "$REPO_DIR/.venv" "$PREVIOUS_VENV"
fi

rollback() {
  trap - ERR
  echo "$(date -Iseconds) activation failed; restoring $LOCAL_REV"
  git reset --hard "$LOCAL_REV" --quiet
  ln -sfn "$PREVIOUS_VENV" "$REPO_DIR/.venv.next"
  mv -Tf "$REPO_DIR/.venv.next" "$REPO_DIR/.venv"
  for unit in "$UNIT_BACKUP"/*; do
    [ ! -f "$unit" ] || install -m644 "$unit" "$UNIT_DIR/$(basename "$unit")"
  done
  systemctl --user daemon-reload
  exit 1
}
trap rollback ERR
git reset --hard "$REMOTE_REV" --quiet
ln -sfn "$RELEASE/venv" "$REPO_DIR/.venv.next"
mv -Tf "$REPO_DIR/.venv.next" "$REPO_DIR/.venv"
for unit in "$RELEASE"/systemd/*.service "$RELEASE"/systemd/*.timer; do
  install -m644 "$unit" "$UNIT_DIR/$(basename "$unit")"
done
systemctl --user daemon-reload
"$REPO_DIR/.venv/bin/polymarket-briefing" validate-config --config "$REPO_DIR/config.yaml"
printf '%s\n' "$REMOTE_REV" > "$STATE_DIR/deployed-revision"
trap - ERR
echo "$(date -Iseconds) deployed ${LOCAL_REV:0:7} -> ${REMOTE_REV:0:7}; runtime=$RELEASE"

# Keep the running release and the previous one (rollback target); drop the
# rest, including releases whose build or tests failed. Never fails the deploy.
bash "$RELEASE/systemd/prune-releases.sh" "$RELEASES_DIR" "$RELEASE" "$PREVIOUS_VENV" ||
  echo "$(date -Iseconds) release pruning failed; continuing"
