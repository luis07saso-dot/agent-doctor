#!/usr/bin/env bash
# Run a temporary demo/test agent locally as a mailbox agent (P6 client, R11 test agent).
#   scripts/temp_agent.sh start <script.py> <port> <workdir>   # needs CLIENT_SEED in env
#   scripts/temp_agent.sh stop  <port> <workdir>               # /disconnect (removes it from
#                                                              # Agentverse), then kill
# Sandbox off (network). Secrets: CLIENT_SEED comes from the caller's env; AGENTVERSE_KEY is
# read from .env into the connect/disconnect call only. Neither is printed or logged.
set -euo pipefail
cd "$(dirname "$0")/.."
cmd="${1:?start|stop}"
key() { grep '^AGENTVERSE_KEY=' .env | head -1 | cut -d= -f2-; }

case "$cmd" in
start)
  script="$2"; port="$3"; dir="$4"
  [ -n "${CLIENT_SEED:-}" ] || { echo "CLIENT_SEED not set" >&2; exit 2; }
  mkdir -p "$dir"
  AGENT_PORT="$port" nohup .venv/bin/python "$script" >"$dir/agent.log" 2>&1 &
  echo $! >"$dir/agent.pid"
  for _ in $(seq 1 30); do
    curl -s -o /dev/null "http://127.0.0.1:$port/agent_info" && break; sleep 1
  done
  curl -s -o /dev/null "http://127.0.0.1:$port/agent_info" || { echo "agent did not start" >&2; exit 1; }
  AGENT_PORT="$port" AGENTVERSE_KEY="$(key)" .venv/bin/python -m agent.connect
  ;;
stop)
  port="$2"; dir="$3"
  body=$(AGENTVERSE_KEY="$(key)" .venv/bin/python -c \
    'import json,os;print(json.dumps({"user_token":os.environ["AGENTVERSE_KEY"]}))')
  res=$(curl -s -X POST -H 'content-type: application/json' --data-binary @- \
    "http://127.0.0.1:$port/disconnect" <<<"$body" || true)
  case "$res" in *'"success": true'*|*'"success":true'*) echo "OK: disconnected (removed from Agentverse)";;
    *) echo "WARN: disconnect did not confirm success" >&2;; esac
  [ -f "$dir/agent.pid" ] && kill "$(cat "$dir/agent.pid")" 2>/dev/null || true
  echo "OK: stopped"
  ;;
*) echo "usage: $0 start|stop ..." >&2; exit 2 ;;
esac
