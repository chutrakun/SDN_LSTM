# Anti_sdn

Anti_sdn is a local SDN security lab composed of a Ryu 4.34/OpenFlow 1.3 controller, a Flask API, a React/Vite dashboard, PostgreSQL persistence, backend-managed Mininet topologies, and an LSTM inference pipeline.

## Portable Installation

Target: Ubuntu/Debian on x86-64. The setup script installs OS packages, Open vSwitch, Mininet, PostgreSQL, a compatible Node.js, pyenv, Python 3.8.18, the `sdn-env38` environment, pinned Python packages, and locked frontend packages. It preserves existing environments and databases and never deletes PostgreSQL data.

```bash
git clone <repository>
cd Anti_sdn
chmod +x scripts/*.sh
./scripts/setup.sh
./scripts/check.sh
./scripts/start.sh
```

After the first installation, normal startup is:

```bash
./scripts/start.sh
```

Services are available at:

```text
Frontend: http://localhost:5173
Backend:  http://localhost:5000
Ryu:      tcp://127.0.0.1:6653
```

The launcher starts only Flask, Ryu, and Vite. Mininet remains owned by the existing backend/dashboard lifecycle. Open the dashboard, select Star, Tree, or Full Mesh, deploy it, and wait for `Ready`/in-sync before running diagnostics. Do not start a competing Mininet instance.

Useful lifecycle commands:

```bash
./scripts/status.sh
./scripts/logs.sh
./scripts/stop.sh
```

`stop.sh` validates every PID against this checkout before signaling it and leaves the system Open vSwitch service running. Routine startup and shutdown never call `mn -c` or use broad `pkill` commands.

## Configuration and secrets

`setup.sh` creates a private, ignored `.env` from `.env.example`, records the intended Python interpreter, and generates a PostgreSQL password when one is not supplied. To configure manually:

```bash
cp .env.example .env
chmod 600 .env
# Edit .env, then rerun setup/check.
```

Important variables include:

- `SDN_MININET_PYTHON`: Python 3.8.18 interpreter containing Ryu, TensorFlow, and Mininet. If empty, scripts use `~/.pyenv/versions/sdn-env38/bin/python`.
- `BACKEND_HOST`, `BACKEND_PORT`, and `BACKEND_URL`: Flask listener and the controller's local API target.
- `FRONTEND_HOST`, `FRONTEND_PORT`, and `VITE_BACKEND_PROXY_TARGET`: Vite listener and development proxy target.
- `RYU_HOST` and `RYU_PORT`: controller address supplied to Mininet; defaults are `127.0.0.1:6653`.
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`: PostgreSQL connection.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: optional notifications. Empty values disable Telegram.

Never commit `.env`. A token previously committed to Git must be considered compromised and rotated at its provider; deleting it from the current source does not erase Git history.

### PostgreSQL

For the default local PostgreSQL configuration, `setup.sh` creates or updates only the configured project role and creates the database if it does not exist. Schema initialization uses the application's existing `CREATE TABLE IF NOT EXISTS` migrations. It does not drop databases, roles, tables, or data. For a remote database, set the `DB_*` variables before running setup; local role/database creation is skipped.

## Verification

Run the preflight whenever configuration changes:

```bash
./scripts/check.sh
```

It verifies required versions, imports, files, model artifacts, a safe model inference, services, privileges, database connectivity when configured, and port availability. An occupied service port is a warning in preflight; `start.sh` will reuse only a process proven by its PID file to belong to this checkout and will refuse unknown listeners.

Once a topology is Ready, the existing safe API diagnostics are:

```bash
curl -s -X POST http://127.0.0.1:5000/api/topology/diagnostics/pingall | jq
curl -s -X POST http://127.0.0.1:5000/api/topology/diagnostics/ping_server | jq
curl -s -X POST http://127.0.0.1:5000/api/topology/diagnostics/http_server | jq
```

Expected results are zero packet loss, successful `h1` to `h_server` reachability, and HTTP status 200.

## Emergency cleanup

Normal lifecycle commands deliberately avoid `mn -c`; the installed Mininet cleanup command may terminate unrelated controller processes. Use `mn -c` only as an explicit offline recovery step after `./scripts/stop.sh`, after verifying Ryu is stopped, and only when stale Mininet state cannot be removed through the dashboard lifecycle.

Legacy root-level scripts are retained for specialized lab recovery and VM routing. They are not part of portable startup and may contain topology-, interface-, or MAC-specific assumptions; review them before use.
