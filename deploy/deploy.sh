#!/usr/bin/env bash
# Deploy committed HEAD to the VPS. Usage: deploy/deploy.sh
# Ships `git archive HEAD` (never the working tree, never .env), builds
# agent-doctor:<sha> on the VPS, keeps the previous tag for rollback.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/common.sh

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Uncommitted changes. Commit first." >&2; exit 1
fi
.venv/bin/python -m pytest -q
SHA="$(git rev-parse --short=12 HEAD)"
echo "Deploying $SHA"

ssh "${SSH_OPTS[@]}" "$VPS_HOST" "mkdir -p $VPS_DIR/releases/$SHA"
git archive HEAD | ssh "${SSH_OPTS[@]}" "$VPS_HOST" "tar -x -C $VPS_DIR/releases/$SHA"
ssh "${SSH_OPTS[@]}" "$VPS_HOST" "bash -s -- $SHA $VPS_DIR $AGENT_ADDRESS" < deploy/remote_install.sh
