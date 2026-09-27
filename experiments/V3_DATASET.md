# Dataset V3 collection framework

V3 remains a controlled Mininet lab dataset. Every generated packet targets
`h_server` at `10.0.0.100`. No V3 model training or Ryu inference integration
is included.

## Design

`v3_collect.py plan` writes 384 planned experiments: four scenarios × four
source hosts × three topologies × four profiles × two replicates. Collection
order interleaves scenarios within each topology/host/profile block. IDs have
form `V3_<topology>_<host>_<scenario>_<profile>_R<replicate>`; manifest fields
also record all factors. Future evaluations should separately hold out R02,
h4, Tree, and p03, keeping all windows from an experiment in one split.

Profiles are:

| Class | p00 | p01 | p02 | p03 |
| --- | --- | --- | --- | --- |
| BENIGN | ping + ordinary HTTP | low-rate UDP to a local UDP sink | paced ordinary HTTP/TCP | idle, then mixed ping/HTTP/UDP bursts |
| UDP_FLOOD | lower steady UDP | medium steady UDP | higher steady UDP | bounded UDP bursts |
| TCP_SYN_LIKE | lower repeated SYN | medium repeated SYN | higher repeated SYN | bounded SYN bursts |
| HTTP_FLOOD | paced HTTP | medium paced HTTP | concurrent HTTP | concurrent HTTP bursts |

The UDP and SYN rate tiers share the same nominal targets and vary by run.
Nominal packet sizes (66, 114, 162, 234 bytes) are assigned independently of
class. UDP and SYN payload lengths compensate for their different header sizes.
HTTP query lengths, concurrency and pauses vary; observed packet sizes and PPS
must still be audited before claiming the design removed shortcuts. Active
durations vary from 22 to 40 seconds, independently of class. BENIGN includes
low-rate and idle windows; its UDP profile uses a temporary sink in h_server.
All processes are bounded and launched inside the existing Mininet namespaces.

## Labels and manifests

The V1 recorder still writes all port windows. `v3_audit.py` assigns a training
label **only** to the source-facing port recorded in a healthy, completed V3
manifest. Every other port is a context observation with an empty training
label. Failed or unhealthy runs are excluded into a separate CSV.

The runner derives host ports from the topology profile and the validated
inter-switch-then-host link order, then checks the actual OVS interface ofport.
It never selects a port using PPS, bytes, or expected behavior. Each manifest
records scenario, host, topology, profile, parameters, exact worker and namespace
commands, source-facing DPID/port, timestamps, readiness, source ofport check,
recorder counts, log path, and post-run ping/HTTP/topology health. It shares the
existing driver's experiment lock and atomic ACTIVE/IDLE state protocol.

The audit reports distributions by scenario, host, topology, and profile for
PPS, byte rates, bytes per packet, and interval, plus missing, nonfinite,
negative, and duplicate-window counts. It keeps source and context CSVs apart.

## Recorder topology readiness

The opt-in recorder uses the selected profile in
`config/current_topology.json` and the authoritative topology definitions.
It requires the project's Mininet PID, exact observed Ryu switch IDs and
directed edges, five seconds of unchanged topology, and a complete subsequent
polling window. Invalid configuration or mismatched runtime state pauses
recording. The existing ACTIVE experiment state and CSV schema checks still
apply. The V3 runner waits for recorder readiness after each topology change.
The currently running Ryu process has `SDN_DATASET_ENABLED=0`; restart that
project-owned process with dataset variables before collecting smoke data.

## Commands

Generate and audit the plan, without traffic:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 experiments/v3_collect.py plan
PYTHONDONTWRITEBYTECODE=1 python3 experiments/v3_audit.py
```

After the recorder gate and lab prerequisites are ready, the four-case smoke
subset can be run with:

```bash
sudo -E python3 experiments/v3_collect.py run-smoke --execute --allow-topology-apply
python3 experiments/v3_audit.py
```

After smoke data has been audited and accepted, the later full collection
command is:

```bash
sudo -E python3 experiments/v3_collect.py run-plan --execute --allow-topology-apply
python3 experiments/v3_audit.py
```

These commands intentionally do not run during framework preparation. The
runner requires a ready backend, recorder status, and Mininet namespaces, and
refuses to overwrite an existing manifest. No `mn -c` or broad process kill is
used.
