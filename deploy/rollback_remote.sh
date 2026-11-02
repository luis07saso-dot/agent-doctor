#!/usr/bin/env bash
# Runs ON THE VPS. Swaps current and previous image tags, restarts.
# Run again to roll forward.
set -euo pipefail
cd "$(dirname "$0")"
exec 9>.lock; flock -w 120 9 || { echo "Another deploy/watchdog holds the lock" >&2; exit 1; }
[ -f .tag.prev ] || { echo "No previous tag to roll back to." >&2; exit 1; }
cp .tag .tag.swap && cp .tag.prev .tag && mv .tag.swap .tag.prev
./dc.sh up -d
echo 0 > .watchdog_strikes
sleep 15
RUNNING="$(docker inspect -f '{{.State.Running}}' agent-doctor 2>/dev/null || echo false)"
echo "now: $(cat .tag) running=$RUNNING"
[ "$RUNNING" = "true" ]
