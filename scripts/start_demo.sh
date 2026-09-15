#!/bin/bash
set -euo pipefail

# shellcheck source=scripts/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
PROJECT_DIR="$ROOT"
LOG_DIR="/tmp/anti_sdn_demo"
mkdir -p "$LOG_DIR"

owned_command() {
    local pid="$1" marker="$2" expected_cwd="${3:-}" command cwd
    [ -n "$pid" ] || return 1
    [ -r "/proc/$pid/cmdline" ] || return 1
    command="$(tr '\0' ' ' <"/proc/$pid/cmdline")"
    case "$command" in *"$marker"*) ;; *) return 1 ;; esac
    if [ -n "$expected_cwd" ]; then
        cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
        [ "$cwd" = "$expected_cwd" ] || return 1
    fi
}

stop_owned() {
    local pid="$1" marker="$2" expected_cwd="${3:-}"
    if owned_command "$pid" "$marker" "$expected_cwd"; then
        kill -TERM "$pid" 2>/dev/null || sudo -n kill -TERM "$pid" 2>/dev/null || true
    fi
}

cleanup() {
    trap - INT TERM EXIT
    stop_owned "${FRONTEND_PID:-}" "npm" "$PROJECT_DIR/frontend"
    stop_owned "${RYU_PID:-}" "$PROJECT_DIR/controller/ryu_controller.py"
    stop_owned "${BACKEND_PID:-}" "$PROJECT_DIR/dashboard_api.py"
    if [ -f /tmp/anti_sdn_topology.pid ]; then
        topo_pid="$(sed -n '1p' /tmp/anti_sdn_topology.pid 2>/dev/null || true)"
        stop_owned "$topo_pid" "$PROJECT_DIR/topology/network_topology.py"
    fi
    # Never run `mn -c` here: on this machine it kills ryu-manager.
}
trap cleanup INT TERM EXIT

cd "$PROJECT_DIR"
python3 dashboard_api.py >"$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
"$PYTHON_BIN" -m ryu.cmd.manager --ofp-tcp-listen-port 6653 --observe-links controller/ryu_controller.py >"$LOG_DIR/ryu.log" 2>&1 &
RYU_PID=$!
(
    cd frontend
    npm run dev -- --host 0.0.0.0
) >"$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!

printf 'Backend: http://localhost:5000\nFrontend: http://localhost:5173\nLogs: %s\n' "$LOG_DIR"
printf 'Select a topology in the web UI and wait for Ready. Press Ctrl-C to clean up.\n'
wait
