#!/bin/sh
# Exit non-zero when the engine or the lead agent card is down.
set -e
curl -fsS http://127.0.0.1:8800/health >/dev/null
curl -fsS http://127.0.0.1:9900/.well-known/agent-card.json >/dev/null
echo "engine and lead agent are up"
