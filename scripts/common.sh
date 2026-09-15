#!/usr/bin/env bash
# Shared path, environment, process, and port helpers for portable launch scripts.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-5000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
RYU_HOST="${RYU_HOST:-127.0.0.1}"
RYU_PORT="${RYU_PORT:-6653}"
RUNTIME_DIR="${ANTI_SDN_RUNTIME_DIR:-/tmp/anti_sdn_$(id -un)}"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"

resolve_sdn_python() {
    if [[ -n "${SDN_MININET_PYTHON:-}" ]]; then
        printf '%s\n' "$SDN_MININET_PYTHON"
    else
        printf '%s\n' "$HOME/.pyenv/versions/sdn-env38/bin/python"
    fi
}

PYTHON_BIN="$(resolve_sdn_python)"

init_runtime_dirs() {
    mkdir -p "$LOG_DIR" "$PID_DIR"
}

pid_from_file() {
    local pid_file="$1" pid
    [[ -r "$pid_file" ]] || return 1
    IFS= read -r pid <"$pid_file"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    printf '%s\n' "$pid"
}

pid_alive() {
    local pid="$1" state
    [[ -d "/proc/" ]] || return 1
    state="$(awk '{print $3}' "/proc//stat" 2>/dev/null || true)"
    [[ "$state" != "Z" ]] && kill -0 "$pid" 2>/dev/null
}

pid_command() {
    local pid="$1"
    [[ -r "/proc/$pid/cmdline" ]] || return 1
    tr '\0' ' ' <"/proc/$pid/cmdline"
}

pid_cwd() {
    readlink "/proc/$1/cwd" 2>/dev/null
}

pid_owned() {
    local pid="$1" marker="$2" expected_cwd="${3:-}" command actual_cwd
    pid_alive "$pid" || return 1
    command="$(pid_command "$pid" 2>/dev/null || true)"
    [[ "$command" == *"$marker"* ]] || return 1
    if [[ -n "$expected_cwd" ]]; then
        actual_cwd="$(pid_cwd "$pid" || true)"
        [[ "$actual_cwd" == "$expected_cwd" ]] || return 1
    fi
}

port_listening() {
    local port="$1"
    ss -ltnH "sport = :$port" 2>/dev/null | grep -q .
}

port_details() {
    local port="$1"
    ss -ltnp "sport = :$port" 2>/dev/null || ss -ltn "sport = :$port" 2>/dev/null || true
}

wait_for_port() {
    local port="$1" timeout="${2:-30}" elapsed=0
    while (( elapsed < timeout * 10 )); do
        port_listening "$port" && return 0
        sleep 0.1
        ((elapsed += 1))
    done
    return 1
}
