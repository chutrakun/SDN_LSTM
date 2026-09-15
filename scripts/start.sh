#!/usr/bin/env bash
set -Eeuo pipefail

# shellcheck source=scripts/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
init_runtime_dirs

[[ -x "$PYTHON_BIN" ]] || {
    printf 'ERROR: Python interpreter not found: %s\nRun ./scripts/setup.sh or set SDN_MININET_PYTHON.\n' "$PYTHON_BIN" >&2
    exit 1
}
[[ -x "$ROOT/frontend/node_modules/.bin/vite" ]] || {
    printf 'ERROR: frontend dependencies are missing; run ./scripts/setup.sh.\n' >&2
    exit 1
}

export BACKEND_HOST BACKEND_PORT RYU_HOST RYU_PORT
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"
export VITE_BACKEND_PROXY_TARGET="${VITE_BACKEND_PROXY_TARGET:-http://127.0.0.1:$BACKEND_PORT}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

STARTED_PIDS=()
STARTED_MARKERS=()
STARTED_CWDS=()
STARTED_FILES=()

rollback_started() {
    local exit_code="$?" index pid
    trap - ERR INT TERM
    printf 'Startup did not complete; stopping only components started by this invocation.\n' >&2
    for ((index=${#STARTED_PIDS[@]}-1; index>=0; index--)); do
        pid="${STARTED_PIDS[$index]}"
        if pid_owned "$pid" "${STARTED_MARKERS[$index]}" "${STARTED_CWDS[$index]}"; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
        rm -f "${STARTED_FILES[$index]}"
    done
    exit "$exit_code"
}
trap rollback_started ERR INT TERM

start_component() {
    local name="$1" port="$2" pid_file="$3" marker="$4" cwd="$5" log_file="$6"
    shift 6
    local existing_pid="" pid pid_tmp

    if existing_pid="$(pid_from_file "$pid_file" 2>/dev/null)"; then
        if pid_owned "$existing_pid" "$marker" "$cwd"; then
            if wait_for_port "$port" 5; then
                printf '[already running] %-8s PID=%s port=%s\n' "$name" "$existing_pid" "$port"
                return 0
            fi
            printf 'ERROR: %s PID %s is owned but port %s is not listening. See %s\n' \
                "$name" "$existing_pid" "$port" "$log_file" >&2
            return 1
        fi
        if pid_alive "$existing_pid"; then
            printf 'ERROR: refusing to replace %s: PID file names unrelated live PID %s\n' "$pid_file" "$existing_pid" >&2
            return 1
        fi
        rm -f "$pid_file"
    fi

    if port_listening "$port"; then
        printf 'ERROR: cannot start %s; port %s belongs to another process:\n' "$name" "$port" >&2
        port_details "$port" >&2
        return 1
    fi

    : >"$log_file"
    (
        cd "$cwd"
        nohup setsid "$@" >>"$log_file" 2>&1 </dev/null &
        printf '%s\n' "$!"
    ) >"$pid_file.tmp"
    IFS= read -r pid <"$pid_file.tmp"
    [[ "$pid" =~ ^[0-9]+$ ]] || {
        printf 'ERROR: failed to capture %s PID\n' "$name" >&2
        return 1
    }
    pid_tmp="$pid_file.tmp"
    mv "$pid_tmp" "$pid_file"
    STARTED_PIDS+=("$pid")
    STARTED_MARKERS+=("$marker")
    STARTED_CWDS+=("$cwd")
    STARTED_FILES+=("$pid_file")

    if ! wait_for_port "$port" 60; then
        printf 'ERROR: %s did not listen on port %s. Log tail:\n' "$name" "$port" >&2
        tail -n 40 "$log_file" >&2 || true
        return 1
    fi
    if ! pid_owned "$pid" "$marker" "$cwd"; then
        printf 'ERROR: %s listener appeared, but PID %s failed ownership validation. Log tail:\n' "$name" "$pid" >&2
        tail -n 40 "$log_file" >&2 || true
        return 1
    fi
    printf '[started]         %-8s PID=%s port=%s log=%s\n' "$name" "$pid" "$port" "$log_file"
}

start_component \
    Backend "$BACKEND_PORT" "$PID_DIR/backend.pid" "$ROOT/dashboard_api.py" "$ROOT" "$LOG_DIR/backend.log" \
    "$PYTHON_BIN" "$ROOT/dashboard_api.py"

start_component \
    Ryu "$RYU_PORT" "$PID_DIR/ryu.pid" "$ROOT/controller/ryu_controller.py" "$ROOT" "$LOG_DIR/ryu.log" \
    "$PYTHON_BIN" -m ryu.cmd.manager --ofp-tcp-listen-port "$RYU_PORT" --observe-links \
    "$ROOT/controller/ryu_controller.py"

start_component \
    Frontend "$FRONTEND_PORT" "$PID_DIR/frontend.pid" "vite" "$ROOT/frontend" "$LOG_DIR/frontend.log" \
    "$ROOT/frontend/node_modules/.bin/vite" --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort

trap - ERR INT TERM
printf '\nAnti_sdn is running.\n'
printf 'Frontend: http://localhost:%s\n' "$FRONTEND_PORT"
printf 'Backend:  http://localhost:%s\n' "$BACKEND_PORT"
printf 'Ryu:      tcp://%s:%s\n' "$RYU_HOST" "$RYU_PORT"
printf 'Logs:     %s\n' "$LOG_DIR"
printf 'Deploy Mininet through the dashboard after all three services are healthy.\n'
