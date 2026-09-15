#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_VERSION="3.8.18"
ENV_NAME="sdn-env38"
SETUP_USER="${SUDO_USER:-$(id -un)}"
SETUP_HOME="$(getent passwd "$SETUP_USER" | cut -d: -f6)"
PYENV_ROOT_DIR="${PYENV_ROOT:-$SETUP_HOME/.pyenv}"
ENV_PYTHON="$PYENV_ROOT_DIR/versions/$ENV_NAME/bin/python"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }

[[ -r /etc/os-release ]] || die "Cannot identify the operating system"
# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}:${ID_LIKE:-}" in
    ubuntu:*|debian:*|*:debian*) ;;
    *) die "This installer targets Ubuntu/Debian; detected ${PRETTY_NAME:-unknown}" ;;
esac
[[ -n "$SETUP_HOME" ]] || die "Cannot determine the home directory for $SETUP_USER"

log "Requesting sudo access for OS services and SDN networking"
sudo -v

log "Installing Ubuntu/Debian packages"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential ca-certificates curl git gnupg jq lsof netcat-openbsd openssl \
    iproute2 iputils-ping procps sudo \
    libbz2-dev libffi-dev liblzma-dev libncurses-dev libreadline-dev \
    libsqlite3-dev libssl-dev libxml2-dev libxmlsec1-dev llvm tk-dev \
    wget xz-utils zlib1g-dev \
    openvswitch-switch mininet postgresql postgresql-client

log "Enabling Open vSwitch and PostgreSQL"
sudo systemctl enable --now openvswitch-switch
sudo systemctl enable --now postgresql

node_usable=false
if command_exists node; then
    node_major="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || printf '0')"
    node_minor="$(node -p 'Number(process.versions.node.split(".")[1])' 2>/dev/null || printf '0')"
    if (( node_major > 22 || (node_major == 22 && node_minor >= 12) || (node_major == 20 && node_minor >= 19) )); then
        node_usable=true
    fi
fi
if [[ "$node_usable" != true ]]; then
    log "Installing Node.js 22 LTS (required by the locked Vite version)"
    keyring="/usr/share/keyrings/nodesource.gpg"
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | sudo gpg --dearmor --yes -o "$keyring"
    printf 'deb [signed-by=%s] https://deb.nodesource.com/node_22.x nodistro main\n' "$keyring" \
        | sudo tee /etc/apt/sources.list.d/nodesource.list >/dev/null
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
fi
command_exists node || die "Node.js installation failed"
command_exists npm || die "npm installation failed"

log "Installing or reusing pyenv"
if [[ ! -x "$PYENV_ROOT_DIR/bin/pyenv" ]]; then
    [[ ! -e "$PYENV_ROOT_DIR" ]] || die "$PYENV_ROOT_DIR exists but is not a usable pyenv installation"
    git clone --depth 1 https://github.com/pyenv/pyenv.git "$PYENV_ROOT_DIR"
fi
export PYENV_ROOT="$PYENV_ROOT_DIR"
export PATH="$PYENV_ROOT/bin:$PATH"

log "Installing or reusing Python $PYTHON_VERSION"
"$PYENV_ROOT/bin/pyenv" install -s "$PYTHON_VERSION"
base_python="$PYENV_ROOT/versions/$PYTHON_VERSION/bin/python"
[[ -x "$base_python" ]] || die "pyenv did not provide Python $PYTHON_VERSION"

log "Creating or reusing $ENV_NAME"
if [[ -e "$PYENV_ROOT/versions/$ENV_NAME" && ! -x "$ENV_PYTHON" ]]; then
    die "$PYENV_ROOT/versions/$ENV_NAME exists but has no executable Python; it was left untouched"
fi
if [[ ! -x "$ENV_PYTHON" ]]; then
    "$base_python" -m venv "$PYENV_ROOT/versions/$ENV_NAME"
fi
actual_python="$($ENV_PYTHON -c 'import platform; print(platform.python_version())')"
[[ "$actual_python" == "$PYTHON_VERSION" ]] \
    || die "$ENV_NAME uses Python $actual_python, expected $PYTHON_VERSION; it was left untouched"
"$PYENV_ROOT/bin/pyenv" rehash

log "Installing pinned Python dependencies"
"$ENV_PYTHON" -m pip install --upgrade 'pip==23.2.1' 'setuptools==58.0.4' 'wheel==0.45.1'
"$ENV_PYTHON" -m pip install --no-build-isolation -r "$ROOT/requirements-sdn.txt"

log "Installing locked frontend dependencies"
(
    cd "$ROOT/frontend"
    npm ci
)

log "Creating local environment configuration"
if [[ ! -e "$ROOT/.env" ]]; then
    umask 077
    cp "$ROOT/.env.example" "$ROOT/.env"
fi
chmod 600 "$ROOT/.env"
if grep -q '^SDN_MININET_PYTHON=$' "$ROOT/.env"; then
    sed -i "s|^SDN_MININET_PYTHON=$|SDN_MININET_PYTHON=$ENV_PYTHON|" "$ROOT/.env"
fi
if grep -q '^DB_PASSWORD=$' "$ROOT/.env"; then
    generated_db_password="$(openssl rand -hex 24)"
    sed -i "s|^DB_PASSWORD=$|DB_PASSWORD=$generated_db_password|" "$ROOT/.env"
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
: "${DB_HOST:=127.0.0.1}"
: "${DB_PORT:=5432}"
: "${DB_NAME:=sdn_security}"
: "${DB_USER:=sdn_user}"
: "${DB_PASSWORD:?DB_PASSWORD must be set in .env}"
[[ "$DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "DB_NAME must be a simple PostgreSQL identifier"
[[ "$DB_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "DB_USER must be a simple PostgreSQL identifier"

if [[ "$DB_HOST" == "127.0.0.1" || "$DB_HOST" == "localhost" ]]; then
    log "Creating or updating the project PostgreSQL role and database"
    sudo -u postgres psql --set=ON_ERROR_STOP=1 \
        --set=db_user="$DB_USER" --set=db_password="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'db_user', :'db_password') \gexec
SQL
    sudo -u postgres psql --set=ON_ERROR_STOP=1 \
        --set=db_name="$DB_NAME" --set=db_user="$DB_USER" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name') \gexec
SQL
else
    log "Remote DB_HOST=$DB_HOST: skipping local role/database creation"
fi

log "Installing the least-privilege commands required by backend-owned Mininet"
sudoers_tmp="$(mktemp)"
trap 'rm -f "$sudoers_tmp"' EXIT
{
    printf '# Generated by %s/scripts/setup.sh\n' "$ROOT"
    printf '%s ALL=(root) NOPASSWD: %s %s/topology/network_topology.py *\n' "$SETUP_USER" "$ENV_PYTHON" "$ROOT"
    printf '%s ALL=(root) NOPASSWD: /usr/bin/kill -TERM *, /usr/bin/kill -KILL *\n' "$SETUP_USER"
    printf '%s ALL=(root) NOPASSWD: /usr/bin/ovs-vsctl *\n' "$SETUP_USER"
    printf '%s ALL=(root) NOPASSWD: /usr/sbin/ip link delete *\n' "$SETUP_USER"
} >"$sudoers_tmp"
chmod 0440 "$sudoers_tmp"
sudo visudo -cf "$sudoers_tmp" >/dev/null
sudo install -o root -g root -m 0440 "$sudoers_tmp" "/etc/sudoers.d/anti-sdn-$SETUP_USER"

log "Initializing the existing database schema (non-destructive CREATE IF NOT EXISTS migrations)"
(
    cd "$ROOT"
    "$ENV_PYTHON" -c 'import db_manager; db_manager.init_db()'
)

log "Installed versions"
printf 'OS:          %s\n' "${PRETTY_NAME:-unknown}"
printf 'Python:      %s\n' "$($ENV_PYTHON --version 2>&1)"
"$ENV_PYTHON" - <<'PY'
from importlib import metadata
for package in ('ryu', 'eventlet', 'tensorflow', 'numpy', 'pandas', 'scikit-learn', 'Flask', 'Flask-Cors', 'psycopg2-binary', 'mininet'):
    print('%-12s %s' % (package + ':', metadata.version(package)))
PY
printf 'Node:        %s\n' "$(node --version)"
printf 'npm:         %s\n' "$(npm --version)"
printf 'Open vSwitch: %s\n' "$(ovs-vsctl --version | head -1)"
printf 'PostgreSQL:  %s\n' "$(psql --version)"
printf '\nSetup complete. Run: %s/scripts/check.sh\n' "$ROOT"
