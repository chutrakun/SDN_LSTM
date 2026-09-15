#!/usr/bin/env bash
set -Eeuo pipefail

# shellcheck source=scripts/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
init_runtime_dirs

component_status() {
    local name="$1" port="$2" pid_file="$3" marker="$4" expected_cwd="${5:-}" pid=""
    if pid="$(pid_from_file "$pid_file" 2>/dev/null)" && pid_owned "$pid" "$marker" "$expected_cwd"; then
        if port_listening "$port"; then
            printf '%-10s RUNNING  PID=%s  port=%s\n' "$name" "$pid" "$port"
        else
            printf '%-10s DEGRADED PID=%s  port=%s not listening\n' "$name" "$pid" "$port"
        fi
    elif port_listening "$port"; then
        printf '%-10s UNKNOWN  no owned PID; port %s is occupied\n' "$name" "$port"
    else
        printf '%-10s STOPPED\n' "$name"
    fi
}

printf 'Anti_sdn status\nProject: %s\nLogs:    %s\n\n' "$ROOT" "$LOG_DIR"
component_status Backend "$BACKEND_PORT" "$PID_DIR/backend.pid" "$ROOT/dashboard_api.py" "$ROOT"
component_status Frontend "$FRONTEND_PORT" "$PID_DIR/frontend.pid" "vite" "$ROOT/frontend"
component_status Ryu "$RYU_PORT" "$PID_DIR/ryu.pid" "$ROOT/controller/ryu_controller.py" "$ROOT"

printf '\nMininet topology\n'
topology_pid="$(pid_from_file /tmp/anti_sdn_topology.pid 2>/dev/null || true)"
if [[ -n "$topology_pid" ]] && pid_owned "$topology_pid" "$ROOT/topology/network_topology.py"; then
    printf 'RUNNING PID=%s command=%s\n' "$topology_pid" "$(pid_command "$topology_pid")"
elif [[ -n "$topology_pid" ]] && pid_alive "$topology_pid"; then
    printf 'REFUSED PID=%s is live but does not match this project topology\n' "$topology_pid"
else
    printf 'STOPPED\n'
fi

printf '\nListening ports\n'
for port in "$BACKEND_PORT" "$FRONTEND_PORT" "$RYU_PORT"; do
    if port_listening "$port"; then
        port_details "$port"
    else
        printf 'port %s: not listening\n' "$port"
    fi
done

printf '\nOVS bridges\n'
if command -v ovs-vsctl >/dev/null 2>&1; then
    bridges="$(ovs-vsctl list-br 2>/dev/null || sudo -n ovs-vsctl list-br 2>/dev/null || true)"
    if [[ -n "$bridges" ]]; then
        printf '%s\n' "$bridges"
    else
        printf '(none or OVS unavailable)\n'
    fi
else
    printf 'ovs-vsctl is not installed\n'
fi

printf '\nBackend topology API\n'
if command -v curl >/dev/null 2>&1 && port_listening "$BACKEND_PORT"; then
    topology_json="$(curl -fsS --max-time 3 "http://127.0.0.1:$BACKEND_PORT/api/topology" 2>/dev/null || true)"
    if [[ -n "$topology_json" ]]; then
        if command -v jq >/dev/null 2>&1; then
            printf '%s\n' "$topology_json" | jq '{status, selected_topology, runtime_topology, in_sync, mininet_running, ryu_available, switches, directed_links, message, error}'
        else
            printf '%s\n' "$topology_json"
        fi
    else
        printf 'API did not return status\n'
    fi
else
    printf 'Backend unavailable\n'
fi
