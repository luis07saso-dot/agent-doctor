#!/usr/bin/env bash
# Q4 audit card on/off without a rebuild: deploy/set_cards.sh on|off   (sandbox off, SSH)
# Sets AUDIT_CARDS in the local .env (never printed), pushes it (push_env.sh), saves the
# container's logs (collector), then recreates the container so it reads the new env.
# Recreating restarts the agent: guard counts and "how do I fix #N" memory reset.
# Needs user approval like any prod change.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/common.sh
case "${1:-}" in
  on) v=1 ;;
  off) v=0 ;;
  *) echo "usage: $0 on|off" >&2; exit 2 ;;
esac
[ -f .env ] || { echo "No local .env" >&2; exit 1; }
tmp=$(mktemp .env.XXXXXX)
chmod 600 "$tmp"
grep -v '^AUDIT_CARDS=' .env > "$tmp" || true
echo "AUDIT_CARDS=$v" >> "$tmp"
mv "$tmp" .env
deploy/push_env.sh
# Same lock as deploy/rollback/watchdog, so the watchdog can't race the recreate.
ssh "${SSH_OPTS[@]}" "$VPS_HOST" "cd $VPS_DIR && exec 9>.lock && flock -w 120 9 \
  && (./collect_logs.sh </dev/null || echo 'log collect failed (continuing)' >&2) \
  && ./dc.sh up -d --force-recreate </dev/null && grep -q '^AUDIT_CARDS=$v\$' .env \
  && sleep 20 && docker inspect -f 'running={{.State.Running}} restarts={{.RestartCount}}' agent-doctor"
echo "OK: cards $1 (AUDIT_CARDS=$v); container recreated"
