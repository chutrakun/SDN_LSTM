#!/usr/bin/env bash
set -Eeuo pipefail

# shellcheck source=scripts/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
init_runtime_dirs

STOP_FAILURES=0
wait_for_exit() {
    local pid="$1" max_attempts="${2:-80}" attempts=0
    while pid_alive "$pid" && (( attempts < max_attempts )); do
        sleep 0.25
        ((attempts += 1))
    done
    ! pid_alive "$pid"
}

signal_pid() {
    local pid="$1" signal="$2" privileged="${3:-false}"
    if [[ "$privileged" == true ]]; then
        kill "-$signal" "$pid" 2>/dev/null || sudo -n /usr/bin/kill "-$signal" "$pid" 2>/dev/null || true
    else
        kill "-$signal" "$pid" 2>/dev/null || true
    fi
}

stop_mininet() {
    local pid_file=/tmp/anti_sdn_topology.pid marker="$ROOT/topology/network_topology.py"
    local file_pid="" candidate
    local -a topology_pids=()
    declare -A seen=()

    if ! file_pid="$(pid_from_file "$pid_file" 2>/dev/null)"; then
        printf '[not running] %-8s (no valid PID file)\n' Mininet
        return 0
    fi
    if ! pid_alive "$file_pid"; then
        printf '[stale PID]  %-8s PID=%s\n' Mininet "$file_pid"
        rm -f "$pid_file"
        return 0
    fi
    if ! pid_owned "$file_pid" "$marker"; then
        printf '[refused]    %-8s PID=%s is alive but is not this project topology\n' Mininet "$file_pid" >&2
        ((STOP_FAILURES += 1))
        return 0
    fi

    while IFS= read -r candidate; do
        [[ "$candidate" =~ ^[0-9]+$ ]] || continue
        [[ -z "${seen[$candidate]:-}" ]] || continue
        if pid_owned "$candidate" "$marker"; then
            topology_pids+=("$candidate")
            seen[$candidate]=1
        fi
    done < <(pgrep -f -- "$marker" 2>/dev/null || true)
    if [[ -z "${seen[$file_pid]:-}" ]]; then
        topology_pids+=("$file_pid")
        seen[$file_pid]=1
    fi

    # The PID file names sudo; signal verified topology children first so the
    # Python SIGTERM handler can call net.stop(), then wait for sudo to reap.
    local child_count=0
    for candidate in "${topology_pids[@]}"; do
        if [[ "$candidate" != "$file_pid" ]] && pid_owned "$candidate" "$marker"; then
            signal_pid "$candidate" TERM true
            ((child_count += 1))
        fi
    done
    if (( child_count == 0 )) && pid_owned "$file_pid" "$marker"; then
        signal_pid "$file_pid" TERM true
    fi
    for candidate in "${topology_pids[@]}"; do
        [[ "$candidate" == "$file_pid" ]] && continue
        wait_for_exit "$candidate" 80 || true
        if pid_alive "$candidate" && pid_owned "$candidate" "$marker"; then
            signal_pid "$candidate" KILL true
            wait_for_exit "$candidate" 20 || true
        fi
    done
    wait_for_exit "$file_pid" 120 || true
    if pid_alive "$file_pid" && pid_owned "$file_pid" "$marker"; then
        signal_pid "$file_pid" TERM true
        wait_for_exit "$file_pid" 40 || true
    fi

    if ! pid_alive "$file_pid"; then
        rm -f "$pid_file"
    elif ! pid_owned "$file_pid" "$marker"; then
        verified_child_alive=false
        for candidate in "${topology_pids[@]}"; do
            if [[ "$candidate" != "$file_pid" ]] && pid_owned "$candidate" "$marker"; then
                verified_child_alive=true
            fi
        done
        if [[ "$verified_child_alive" == false ]]; then
            # The topology child is gone; never signal a changed sudo monitor.
            rm -f "$pid_file"
        fi
    fi
    if [[ -e "$pid_file" ]]; then
        printf '[failed]     %-8s topology PID file remains: %s\n' Mininet "$pid_file" >&2
        ((STOP_FAILURES += 1))
    else
        printf '[stopped]    %-8s PIDs=%s\n' Mininet "${topology_pids[*]}"
    fi
}

stop_owned_pid() {
    local name="$1" pid_file="$2" marker="$3" expected_cwd="${4:-}" pid=""
    if ! pid="$(pid_from_file "$pid_file" 2>/dev/null)"; then
        printf '[not running] %-8s (no valid PID file)\n' "$name"
        return 0
    fi
    if ! pid_alive "$pid"; then
        printf '[stale PID]  %-8s PID=%s\n' "$name" "$pid"
        rm -f "$pid_file"
        return 0
    fi
    if ! pid_owned "$pid" "$marker" "$expected_cwd"; then
        printf '[refused]    %-8s PID=%s is alive but is not owned by this project\n' "$name" "$pid" >&2
        ((STOP_FAILURES += 1))
        return 0
    fi

    signal_pid "$pid" TERM false
    if ! wait_for_exit "$pid" 40 && pid_owned "$pid" "$marker" "$expected_cwd"; then
        signal_pid "$pid" KILL false
        wait_for_exit "$pid" 20 || true
    fi
    if pid_alive "$pid"; then
        printf '[failed]     %-8s PID=%s did not stop; no unrelated process was signaled\n' "$name" "$pid" >&2
        ((STOP_FAILURES += 1))
    else
        rm -f "$pid_file"
        printf '[stopped]    %-8s PID=%s\n' "$name" "$pid"
    fi
}

# Safe shutdown order: backend-owned topology, frontend, Ryu, backend.
stop_mininet
stop_owned_pid Frontend "$PID_DIR/frontend.pid" vite "$ROOT/frontend"
stop_owned_pid Ryu "$PID_DIR/ryu.pid" "$ROOT/controller/ryu_controller.py" "$ROOT"
stop_owned_pid Backend "$PID_DIR/backend.pid" "$ROOT/dashboard_api.py" "$ROOT"

for entry in "Backend:$BACKEND_PORT" "Frontend:$FRONTEND_PORT" "Ryu:$RYU_PORT"; do
    name="${entry%%:*}"
    port="${entry##*:}"
    if port_listening "$port"; then
        printf '[notice]     %-8s port %s still belongs to a process not stopped by this script\n' "$name" "$port"
        port_details "$port"
    fi
done

printf 'Open vSwitch was left running. Logs remain in %s\n' "$LOG_DIR"
(( STOP_FAILURES == 0 ))
