#!/usr/bin/env bash
# Runs ON THE VPS from /etc/cron.d/agent-doctor every 10 min. Arg: agent address.
# Restart after 2 consecutive non-active checks (status != "active", or 404).
# Agentverse API errors are not strikes (restarting would not help) and do not
# reset the count. Skips quietly while a deploy/rollback holds the lock.
set -uo pipefail
ADDR="$1"
DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="$DIR/.watchdog_strikes"
LOG=/var/log/agent-doctor-watchdog.log
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

exec 9>"$DIR/.lock"; flock -n 9 || { log "locked by deploy, skip"; exit 0; }

if [ "$(docker inspect -f '{{.State.Running}}' agent-doctor 2>/dev/null)" != "true" ]; then
  log "container not running -> up -d"
  "$DIR/dc.sh" up -d >/dev/null 2>&1 || log "up -d failed"
  echo 0 > "$STATE"; exit 0
fi

STRIKES="$(cat "$STATE" 2>/dev/null || echo 0)"
case "$STRIKES" in ''|*[!0-9]*) STRIKES=0 ;; esac
BODY="$(mktemp)"
CODE="$(curl -s -m 10 -o "$BODY" -w '%{http_code}' "https://agentverse.ai/v1/almanac/agents/$ADDR")"
if [ "$CODE" = "200" ] && grep -Eq '"status"[[:space:]]*:[[:space:]]*"active"' "$BODY"; then
  [ "$STRIKES" != "0" ] && log "active again (was $STRIKES strikes)"
  STRIKES=0
elif [ "$CODE" = "200" ] || [ "$CODE" = "404" ]; then
  STRIKES=$((STRIKES + 1)); log "not active http=$CODE strike=$STRIKES"
else
  log "agentverse api error http=$CODE (no strike)"
fi
rm -f "$BODY"

if [ "$STRIKES" -ge 2 ]; then
  log "restarting agent-doctor"
  "$DIR/dc.sh" restart agent >/dev/null 2>&1 || log "restart failed"
  STRIKES=0
fi
echo "$STRIKES" > "$STATE"
