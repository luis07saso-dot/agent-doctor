#!/usr/bin/env bash
# Install only the R9/R10 log collector on the VPS, without redeploying the agent.
# Usage: deploy/install_collector.sh   (needs SSH; run with the sandbox off)
# Copies deploy/collect_logs.sh to $VPS_DIR, adds /etc/cron.d/agent-doctor-collect (every
# 5 min), runs it once. Next deploy/deploy.sh reinstalls both from the release.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/common.sh

ssh "${SSH_OPTS[@]}" "$VPS_HOST" "cat > $VPS_DIR/collect_logs.sh.new && chmod 755 $VPS_DIR/collect_logs.sh.new && mv $VPS_DIR/collect_logs.sh.new $VPS_DIR/collect_logs.sh" < deploy/collect_logs.sh
ssh "${SSH_OPTS[@]}" "$VPS_HOST" "bash -s -- $VPS_DIR" <<'REMOTE'
set -euo pipefail
DIR="$1"
cat > /etc/cron.d/agent-doctor-collect <<CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * root $DIR/collect_logs.sh >/dev/null 2>&1
CRON
chmod 644 /etc/cron.d/agent-doctor-collect
"$DIR/collect_logs.sh"
echo "collector installed: $(wc -l < "$DIR/logs/events.log" 2>/dev/null || echo 0) events in $DIR/logs/events.log"
REMOTE
