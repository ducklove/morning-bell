#!/usr/bin/env bash
# Delete old release directories, keeping the ones the given paths live in.
#
# Usage: prune-releases.sh RELEASES_DIR KEEP_PATH...
#
# deploy.sh calls this after a successful switch with the new release and the
# previous .venv target, so the running release and one rollback target stay.
# Only direct children named "<40-hex revision>-<YYYYmmddTHHMMSS>-<pid>" are
# ever removed; anything else in the directory is left alone. Failures here
# never fail a deployment.
set -uo pipefail

releases_dir="${1:-}"
[ -n "$releases_dir" ] || { echo "usage: $0 RELEASES_DIR KEEP_PATH..." >&2; exit 2; }
shift
[ -d "$releases_dir" ] || exit 0
root="$(readlink -f -- "$releases_dir")" || exit 1
case "$root" in
  "" | "/" | "$HOME") echo "refusing to prune $root" >&2; exit 1 ;;
esac

# Top-level entry names to keep, one per line.
keep=""
for path in "$@"; do
  [ -n "$path" ] || continue
  resolved="$(readlink -f -- "$path" 2>/dev/null)" || continue
  # GNU readlink -f tolerates a missing last component; a kept path must exist.
  [ -e "$resolved" ] || continue
  case "$resolved" in
    "$root"/*)
      rel="${resolved#"$root"/}"
      keep="$keep${rel%%/*}"$'\n'
      ;;
  esac
done
# Never prune blind: if nothing to keep resolved inside the directory, the
# caller passed the wrong paths and deleting would remove the live release.
[ -n "$keep" ] || { echo "no kept release under $root; not pruning" >&2; exit 1; }

pattern='^[0-9a-f]{40}-[0-9]{8}T[0-9]{6}-[0-9]+$'
status=0
for entry in "$root"/*; do
  [ -d "$entry" ] && [ ! -L "$entry" ] || continue
  name="$(basename -- "$entry")"
  [[ "$name" =~ $pattern ]] || continue
  if printf '%s' "$keep" | grep -qxF -- "$name"; then
    continue
  fi
  if rm -rf -- "$entry"; then
    echo "pruned release $name"
  else
    echo "could not prune release $name" >&2
    status=1
  fi
done
exit "$status"
