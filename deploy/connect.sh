#!/usr/bin/env bash
# Connect the mailbox / republish profile. Runs agent.connect inside the container.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/common.sh
ssh "${SSH_OPTS[@]}" "$VPS_HOST" "$VPS_DIR/dc.sh exec -T agent python -m agent.connect"
