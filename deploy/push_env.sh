#!/usr/bin/env bash
# Copy local .env to the VPS (chmod 600). Contents are piped, never printed.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/common.sh
[ -f .env ] || { echo "No local .env" >&2; exit 1; }
for k in AGENT_SEED_PHRASE AGENTVERSE_KEY; do
  grep -q "^$k=." .env || { echo "$k missing in .env" >&2; exit 1; }
done
ssh "${SSH_OPTS[@]}" "$VPS_HOST" "mkdir -p $VPS_DIR && umask 077 && cat > $VPS_DIR/.env" < .env
echo "OK: .env pushed (contents not shown)"
