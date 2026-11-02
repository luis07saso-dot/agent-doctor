#!/usr/bin/env bash
# Roll the VPS back to the previous image tag (run again to roll forward).
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/common.sh
ssh "${SSH_OPTS[@]}" "$VPS_HOST" "$VPS_DIR/rollback_remote.sh"
