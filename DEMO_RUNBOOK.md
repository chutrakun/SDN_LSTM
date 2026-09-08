# Instructor demo runbook

## 1. Project and startup

Project directory:

```bash
cd /home/beepbeep-kun/Anti_sdn
```

Start the complete demo in one terminal:

```bash
./scripts/start_demo.sh
```

Or start each service in its own terminal:

```bash
cd /home/beepbeep-kun/Anti_sdn
python3 dashboard_api.py
```

```bash
cd /home/beepbeep-kun/Anti_sdn
/home/beepbeep-kun/.pyenv/versions/sdn-env38/bin/ryu-manager \
  --ofp-tcp-listen-port 6653 --observe-links controller/ryu_controller.py
```

```bash
cd /home/beepbeep-kun/Anti_sdn/frontend
npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173`. The API is `http://localhost:5000`; Ryu listens on TCP `6653`.

## 2. Topology selection and READY

The page first performs `GET /api/topology`; it never POSTs a local default. Choosing Star, Tree, or Full Mesh sends the validated ID to `POST /api/topology`. The backend atomically saves it in `config/current_topology.json`, restarts only this project's Mininet runtime, and waits for Ryu discovery. Ryu stays running.

READY means `status` is `ready` (or `running`), `in_sync` is `true`, and the graph matches the selected profile:

- Star: 1 switch / 0 directed inter-switch links
- Tree: 3 switches / 4 directed inter-switch links
- Full Mesh: 4 switches / 12 directed inter-switch links

Check directly:

```bash
curl -s http://localhost:5000/api/topology | jq
```

## 3. Connectivity checks

```bash
curl -s -X POST http://localhost:5000/api/topology/diagnostics/pingall | jq
curl -s -X POST http://localhost:5000/api/topology/diagnostics/ping_server | jq
curl -s -X POST http://localhost:5000/api/topology/diagnostics/http_server | jq
```

Expected after READY: `packet_loss_percent: 0.0`, `h1` can ping `h_server` (`10.0.0.100`), and the HTTP diagnostic returns `200`.

## 4. Restart Ryu only

Do not POST a topology and do not restart backend or Mininet. Identify and inspect the listener first:

```bash
sudo ss -ltnp '( sport = :6653 )'
tr '\0' ' ' </proc/RYU_PID/cmdline
readlink /proc/RYU_PID/cwd
kill -TERM RYU_PID
```

Then rerun the Ryu command from section 1. The topology PID and config hash must remain unchanged; within about 60 seconds, the persisted selection should return to READY/in-sync.

## 5. Safe cleanup and emergency recovery

Normal UI topology changes already use project-scoped cleanup: verified topology PIDs, verified `s1`-`s4` bridges attached to `tcp:127.0.0.1:6653`, and switch-side project interfaces only. `Ctrl-C` in `scripts/start_demo.sh` terminates only the PIDs it started and the verified topology PID.

> **WARNING:** On this machine, `mn -c` invokes cleanup that kills `ryu-manager`.
>
> **NEVER use `mn -c` while Ryu is expected to stay running.** Routine topology changes and routine shutdown do not need it. Use `mn -c` only for full/offline emergency recovery after Ryu has intentionally stopped and its TCP 6653 listener is confirmed absent.

For emergency recovery: stop the exact owned backend, Ryu, and topology PIDs with SIGTERM; wait for them to exit; confirm ports 5000/6653 and the topology PID are gone. Only then may `sudo mn -c` be used. Restart the three services with the commands in section 1. The selection in `config/current_topology.json` persists; use the web selector to start that selected topology if Mininet is offline.
