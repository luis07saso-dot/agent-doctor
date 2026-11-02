#!/usr/bin/env bash
# Runs ON THE VPS via deploy.sh. Args: <sha> <dir> <agent_address>
# Tags are promoted only after the smoke test passes. On failure the previous
# tag is restored, so .tag/.tag.prev always point at known-good releases.
set -euo pipefail
SHA="$1"; DIR="$2"; ADDR="$3"
REL="$DIR/releases/$SHA"
cd "$DIR"
exec 9>"$DIR/.lock"; flock -w 120 9 || { echo "Another deploy/watchdog holds the lock" >&2; exit 1; }

[ -f .env ] || { echo "Missing $DIR/.env. Run deploy/push_env.sh first." >&2; exit 1; }
chmod 600 .env

docker build -q -t "agent-doctor:$SHA" "$REL" >/dev/null </dev/null
install -m 644 "$REL/docker-compose.yml" docker-compose.yml
install -m 755 "$REL/deploy/dc.sh" dc.sh
install -m 755 "$REL/deploy/watchdog.sh" watchdog.sh
install -m 755 "$REL/deploy/rollback_remote.sh" rollback_remote.sh

CUR="$(sed -n 's/^TAG=//p' .tag 2>/dev/null || true)"
echo "TAG=$SHA" > .tag.candidate
docker compose --env-file .tag.candidate up -d --remove-orphans </dev/null

# Smoke: container must stay up 20s with zero restarts.
sleep 20
RUNNING="$(docker inspect -f '{{.State.Running}}' agent-doctor 2>/dev/null || echo false)"
RESTARTS="$(docker inspect -f '{{.RestartCount}}' agent-doctor 2>/dev/null || echo -1)"
echo "running=$RUNNING restarts=$RESTARTS tag=$SHA"
if [ "$RUNNING" != "true" ] || [ "$RESTARTS" != "0" ]; then
  rm -f .tag.candidate
  if [ -n "$CUR" ]; then
    echo "SMOKE FAILED. Restoring $CUR" >&2
    ./dc.sh up -d </dev/null
  else
    echo "SMOKE FAILED. No previous tag to restore." >&2
  fi
  exit 1
fi

# Promote.
if [ -n "$CUR" ] && [ "$CUR" != "$SHA" ]; then echo "TAG=$CUR" > .tag.prev; fi
mv .tag.candidate .tag
echo 0 > .watchdog_strikes

# Watchdog: every 10 min, restart after 2 consecutive non-active checks.
cat > /etc/cron.d/agent-doctor <<CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/10 * * * * root $DIR/watchdog.sh $ADDR >/dev/null 2>&1
CRON
chmod 644 /etc/cron.d/agent-doctor
cat > /etc/logrotate.d/agent-doctor <<ROT
/var/log/agent-doctor-watchdog.log {
  weekly
  rotate 4
  compress
  missingok
  notifempty
}
ROT

# Keep only current + previous images and releases.
PREV="$(sed -n 's/^TAG=//p' .tag.prev 2>/dev/null || true)"
for t in $(docker images agent-doctor --format '{{.Tag}}'); do
  [ "$t" = "$SHA" ] || [ "$t" = "$PREV" ] || docker rmi -f "agent-doctor:$t" >/dev/null || true
done
find "$DIR/releases" -mindepth 1 -maxdepth 1 -type d ! -name "$SHA" ! -name "${PREV:-none}" -exec rm -r {} +
echo "Deploy OK: $SHA (prev: ${PREV:-none})"
