#!/usr/bin/env bash
# R9/R10 log collector. Runs ON THE VPS from /etc/cron.d/agent-doctor-collect every 5 min,
# and once from remote_install.sh before a deploy replaces the container (a new container
# starts with empty logs). Copies the few log lines metrics need into a file that Docker
# rotation and container re-creation can't drop.
#
# Output: $DIR/logs/events.log, one line per event, "<docker RFC3339Nano UTC ts> <KIND> ...":
#   REQ {json}                 request log line (hashed ids, no message text; agent/chat.py)
#   MAILBOX_ERR status=<code>  failed mailbox poll: HTTP code, 404, connect or exception
#   HEARTBEAT almanac          hourly "Registration on Almanac API successful" (uagents)
#   START                      agent process started
#   HANDLER_ERR                one of our handlers failed (exception type only, never text)
# Mailbox error bodies are dropped: only the status code is kept.
#
# Docker prints fixed-width timestamps (9-digit nanoseconds, Z), so string compare = time
# compare. `--since` is inclusive, so lines at or before the last saved timestamp are skipped.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$DIR/logs"
OUT="$OUT_DIR/events.log"
STATE="$OUT_DIR/.since"
CONTAINER="${1:-agent-doctor}"

mkdir -p "$OUT_DIR"
exec 8>"$OUT_DIR/.collect.lock"; flock -n 8 || exit 0
docker inspect "$CONTAINER" >/dev/null 2>&1 || exit 0  # no container yet: nothing to read

SINCE="$(cat "$STATE" 2>/dev/null || true)"
ARGS=(--timestamps)
[ -n "$SINCE" ] && ARGS+=(--since "$SINCE")

TMP="$(mktemp "$OUT_DIR/.collect.XXXXXX")" || exit 1
trap 'rm -f "$TMP"' EXIT
docker logs "${ARGS[@]}" "$CONTAINER" 2>&1 | awk -v last="$SINCE" '
  $1 <= last { next }
  { ts = $1 }
  / REQ \{/                                   { sub(/^.* REQ \{/, "{"); print ts, "REQ", $0; next }
  /Failed to retrieve messages: [0-9]+:/      { match($0, /Failed to retrieve messages: [0-9]+/)
                                                code = substr($0, RSTART + 29, RLENGTH - 29)
                                                print ts, "MAILBOX_ERR status=" code; next }
  /Failed to connect to mailbox server/       { print ts, "MAILBOX_ERR status=connect"; next }
  /Got exception while checking mailbox/      { print ts, "MAILBOX_ERR status=exception"; next }
  /Agent mailbox not found/                   { print ts, "MAILBOX_ERR status=404"; next }
  /Registration on Almanac API successful/    { print ts, "HEARTBEAT almanac"; next }
  /Starting agent with address/               { print ts, "START"; next }
  /handler failed: [A-Za-z_]+/                { print ts, "HANDLER_ERR"; next }
' > "$TMP"

if [ -s "$TMP" ]; then
  cat "$TMP" >> "$OUT"
  tail -n 1 "$TMP" | cut -d' ' -f1 > "$STATE"
fi
chmod 600 "$OUT" 2>/dev/null || true
