#!/bin/bash
# Ryu-only watchdog. Mininet topology lifecycle is owned by dashboard_api.py.

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RYU_APP="$PROJECT_DIR/controller/ryu_controller.py"
RYU_BIN="/home/beepbeep-kun/.pyenv/versions/sdn-env38/bin/ryu-manager"
WAIT_BEFORE_RESTART=3
MAX_RESTARTS=20
RESTART_COUNT=0

printf 'Ryu watchdog started\n  App: %s\n  Mininet owner: dashboard backend\n' "$RYU_APP"

while true; do
    printf '[%s] Starting Ryu (restart #%s)\n' "$(date '+%H:%M:%S')" "$RESTART_COUNT"
    cd "$PROJECT_DIR" || exit 1
    "$RYU_BIN" --ofp-tcp-listen-port 6653 --observe-links "$RYU_APP"
    EXIT_CODE=$?
    printf '[%s] Ryu exited (code=%s)\n' "$(date '+%H:%M:%S')" "$EXIT_CODE"
    RESTART_COUNT=$((RESTART_COUNT + 1))
    if [ "$RESTART_COUNT" -ge "$MAX_RESTARTS" ]; then
        printf 'Reached max restarts (%s).\n' "$MAX_RESTARTS"
        exit 1
    fi
    sleep "$WAIT_BEFORE_RESTART"
done
