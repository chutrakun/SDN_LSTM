#!/usr/bin/env bash
set -Eeuo pipefail

# shellcheck source=scripts/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
pass() { printf '[✓] %s\n' "$*"; ((PASS_COUNT += 1)); }
warn() { printf '[!] %s\n' "$*"; ((WARN_COUNT += 1)); }
fail() { printf '[✗] %s\n' "$*"; ((FAIL_COUNT += 1)); }

printf 'Anti_sdn preflight\nProject: %s\n\n' "$ROOT"

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    case "${ID:-}:${ID_LIKE:-}" in
        ubuntu:*|debian:*|*:debian*) pass "OS ${PRETTY_NAME:-$ID}" ;;
        *) fail "Unsupported OS ${PRETTY_NAME:-unknown}; Ubuntu/Debian required" ;;
    esac
else
    fail "Cannot read /etc/os-release"
fi

if [[ -x "$PYTHON_BIN" ]]; then
    python_version="$($PYTHON_BIN -c 'import platform; print(platform.python_version())' 2>&1 || true)"
    if [[ "$python_version" == "3.8.18" ]]; then
        pass "Python $python_version ($PYTHON_BIN)"
    else
        fail "Python $python_version at $PYTHON_BIN (expected 3.8.18)"
    fi
else
    fail "Python interpreter missing: $PYTHON_BIN"
fi

check_package() {
    local distribution="$1" expected="$2" label="${3:-$1}" actual
    if [[ ! -x "$PYTHON_BIN" ]]; then
        fail "$label import not tested because Python is unavailable"
        return
    fi
    actual="$($PYTHON_BIN - "$distribution" <<'PY' 2>/dev/null || true
from importlib import metadata
import sys
try:
    print(metadata.version(sys.argv[1]))
except metadata.PackageNotFoundError:
    pass
PY
)"
    if [[ "$actual" == "$expected" ]]; then
        pass "$label $actual"
    elif [[ -n "$actual" ]]; then
        fail "$label $actual (expected $expected)"
    else
        fail "$label is not installed"
    fi
}

check_package ryu 4.34 Ryu
check_package eventlet 0.30.2 eventlet
check_package tensorflow 2.13.1 TensorFlow
check_package numpy 1.24.3 NumPy
check_package pandas 2.0.3 pandas
check_package scikit-learn 1.3.2 scikit-learn
check_package joblib 1.4.2 joblib
check_package Flask 3.0.3 Flask
check_package Flask-Cors 5.0.0 Flask-Cors
check_package psycopg2-binary 2.9.10 psycopg2-binary
check_package python-dotenv 1.0.1 python-dotenv

if [[ -x "$PYTHON_BIN" ]] && "$PYTHON_BIN" -c 'import ryu, tensorflow, numpy, flask, psycopg2' >/dev/null 2>&1; then
    pass "Core Python imports"
else
    fail "One or more core Python imports failed"
fi
if [[ -x "$PYTHON_BIN" ]] && "$PYTHON_BIN" -c 'import mininet; print(mininet.__file__)' >/dev/null 2>&1; then
    pass "Mininet Python module available"
else
    fail "Mininet is not importable by the intended interpreter"
fi
mn_bin="$(dirname "$PYTHON_BIN")/mn"
if [[ -x "$mn_bin" ]]; then
    pass "Mininet command available ($mn_bin)"
elif command -v mn >/dev/null 2>&1; then
    warn "Mininet command exists outside the SDN environment; topology import must still pass"
else
    fail "Mininet command unavailable"
fi

if command -v ovs-vsctl >/dev/null 2>&1; then
    pass "ovs-vsctl available ($(ovs-vsctl --version | head -1))"
else
    fail "ovs-vsctl unavailable"
fi
if systemctl is-active --quiet openvswitch-switch 2>/dev/null; then
    pass "Open vSwitch active"
else
    fail "Open vSwitch service is not active"
fi

if command -v node >/dev/null 2>&1; then
    node_version="$(node --version)"
    node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
    node_minor="$(node -p 'Number(process.versions.node.split(".")[1])')"
    if (( node_major > 22 || (node_major == 22 && node_minor >= 12) || (node_major == 20 && node_minor >= 19) )); then
        pass "Node $node_version"
    else
        fail "Node $node_version is too old for Vite 8 (need >=20.19 or >=22.12)"
    fi
else
    fail "Node unavailable"
fi
if command -v npm >/dev/null 2>&1; then
    pass "npm $(npm --version)"
else
    fail "npm unavailable"
fi

if command -v psql >/dev/null 2>&1; then
    pass "PostgreSQL client ($(psql --version))"
else
    fail "PostgreSQL client unavailable"
fi
if systemctl is-active --quiet postgresql 2>/dev/null; then
    pass "PostgreSQL service active"
else
    fail "PostgreSQL service is not active"
fi

required_files=(
    controller/ryu_controller.py
    dashboard_api.py
    db_manager.py
    notifier.py
    topology/network_topology.py
    topology/topology_config.py
    topology/topology_manager.py
    frontend/package.json
    frontend/package-lock.json
    config/current_topology.json
    requirements-sdn.txt
)
for relative in "${required_files[@]}"; do
    if [[ -f "$ROOT/$relative" ]]; then
        pass "$relative"
    else
        fail "Missing required file: $relative"
    fi
done
if [[ -d "$ROOT/frontend/node_modules" ]]; then
    pass "frontend/node_modules installed"
else
    fail "frontend dependencies missing; run scripts/setup.sh"
fi

model_files=(
    ml/model/lstm_sdn_model.h5
    ml/model/scaler.pkl
    ml/model/label_encoder.pkl
)
for relative in "${model_files[@]}"; do
    if [[ -s "$ROOT/$relative" ]]; then
        pass "$relative"
    else
        fail "Missing or empty ML artifact: $relative"
    fi
done

if [[ -x "$PYTHON_BIN" ]] && model_output="$(
    cd "$ROOT"
    TF_CPP_MIN_LOG_LEVEL=2 "$PYTHON_BIN" - <<'PY' 2>&1
import joblib
import numpy as np
import tensorflow as tf

model = tf.keras.models.load_model('ml/model/lstm_sdn_model.h5', compile=False)
scaler = joblib.load('ml/model/scaler.pkl')
encoder = joblib.load('ml/model/label_encoder.pkl')
features = np.array([[80, 6, 1_000_000, 100, 0, 50_000, 0, 400_000, 100, 10_000]], dtype=float)
scaled = scaler.transform(features)
expected_features = int(model.input_shape[-1])
if scaled.shape != (1, expected_features):
    raise RuntimeError('scaled shape %r is incompatible with model input %r' % (scaled.shape, model.input_shape))
prediction = model.predict(scaled.reshape(1, 1, expected_features), verbose=0)
if prediction.shape[-1] != len(encoder.classes_):
    raise RuntimeError('model outputs %s classes but encoder has %s' % (prediction.shape[-1], len(encoder.classes_)))
label = encoder.inverse_transform([int(np.argmax(prediction[0]))])[0]
print('input=%s scaler_features=%s outputs=%s label=%s' % (model.input_shape, scaler.n_features_in_, prediction.shape[-1], label))
PY
)"; then
    pass "LSTM smoke inference ($model_output)"
else
    fail "LSTM smoke inference failed: ${model_output:-no output}"
fi

if [[ -f "$ENV_FILE" ]]; then
    pass ".env exists and is ignored"
else
    fail ".env missing; run scripts/setup.sh or copy .env.example"
fi
if [[ -n "${DB_NAME:-}" && -n "${DB_USER:-}" && -n "${DB_PASSWORD:-}" ]]; then
    pass "Required database variables are set"
    if DB_CONNECT_OUTPUT="$(cd "$ROOT"; "$PYTHON_BIN" - <<'PY' 2>&1
import db_manager
with db_manager.get_conn() as connection:
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database(), current_user')
        database, user = cursor.fetchone()
print('%s as %s' % (database, user))
PY
)"; then
        pass "Database connectivity ($DB_CONNECT_OUTPUT)"
    else
        fail "Database connectivity failed: $DB_CONNECT_OUTPUT"
    fi
else
    warn "DB_NAME, DB_USER, or DB_PASSWORD is unset; database-backed features are unavailable"
fi
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    pass "Telegram variables configured"
else
    warn "Telegram notifications are disabled (optional variables unset)"
fi

if sudo -n "$PYTHON_BIN" "$ROOT/topology/network_topology.py" --help >/dev/null 2>&1; then
    pass "Passwordless project-scoped Mininet launch permission"
else
    fail "Backend cannot launch Mininet non-interactively; rerun scripts/setup.sh"
fi

for entry in "Backend:$BACKEND_PORT" "Frontend:$FRONTEND_PORT" "Ryu:$RYU_PORT"; do
    name="${entry%%:*}"
    port="${entry##*:}"
    if port_listening "$port"; then
        warn "$name port $port is already listening: $(port_details "$port" | tail -1)"
    else
        pass "$name port $port is available"
    fi
done

legacy_user_path="/home/beepbeep""-kun"
if hardcoded_hits="$(rg -n -I --hidden -g '!.git/**' -g '!frontend/node_modules/**' -g '!data/pilot/**' -g '!*.log' "$legacy_user_path" "$ROOT" 2>/dev/null)" && [[ -n "$hardcoded_hits" ]]; then
    fail "Machine-specific user paths remain in runtime/source files: $hardcoded_hits"
else
    pass "No active machine-specific user paths"
fi

printf '\nPASS=%d WARN=%d FAIL=%d\n' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
(( FAIL_COUNT == 0 ))
