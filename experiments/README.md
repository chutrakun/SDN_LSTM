# SDN traffic experiment driver

`traffic_experiment_driver.py` runs one bounded traffic scenario in an
already-running Mininet network. All targets are fixed inside the local
experiment network. The driver refuses to start until the recorder reports four
datapaths, twelve directed links, five seconds of topology stability, and one
complete post-readiness polling window. An exclusive lock prevents overlapping
experiments.

Start Ryu with recording and its atomic experiment-state interface enabled:

```bash
export SDN_DATASET_ENABLED=1
export SDN_DATASET_PATH=/tmp/pilot.csv
export SDN_DATASET_STATE_PATH=/tmp/sdn_experiment_state.json
export SDN_DATASET_STATUS_PATH=/tmp/sdn_dataset_status.json
ryu-manager --observe-links controller/ryu_controller.py
```

The controller stays running while the driver changes explicit experiment
metadata through `SDN_DATASET_STATE_PATH`. The controller environment variables
select the state and status files; the driver writes the scenario label,
experiment ID, and attack source atomically. Missing, malformed, inactive, or
expired state pauses recording. Model predictions never supply labels.

Run one scenario at a time, for example:

```bash
sudo experiments/traffic_experiment_driver.py BENIGN \
  --experiment-id pilot-benign-01 --duration 20
sudo experiments/traffic_experiment_driver.py UDP_FLOOD \
  --experiment-id pilot-udp-01 --duration 15 --udp-pps 500
sudo experiments/traffic_experiment_driver.py TCP_SYN_LIKE \
  --experiment-id pilot-syn-01 --duration 15 --syn-pps 250
sudo experiments/traffic_experiment_driver.py HTTP_FLOOD \
  --experiment-id pilot-http-01 --duration 15 --http-concurrency 4
```

Each experiment has WARMUP, ACTIVE, and COOLDOWN phases. The ACTIVE state is
published one second before traffic starts so the recorder can observe it.
Only polling windows wholly contained between the planned ACTIVE timestamps are
written with the final scenario label. WARMUP and COOLDOWN windows are excluded.
Every run writes a JSON manifest containing timestamps, target, source, exact
namespace and traffic commands, duration, parameters, readiness evidence, and
completion status.

The scenarios are:

- `BENIGN`: h1 sends one ping and one normal HTTP GET per cycle. Its
  `attack_source_host` metadata is `none`.
- `UDP_FLOOD`: h2 sends bounded-rate UDP packets to h_server port 9000.
- `TCP_SYN_LIKE`: h3 sends repeated TCP SYN packets to h_server port 80. This
  is a synthetic SYN-like workload.
- `HTTP_FLOOD`: h4 issues repeated HTTP GET batches against h_server with
  bounded concurrency.

The labels describe these commands exactly. They are not CICIDS `DrDoS_DNS`,
`UDP-lag`, or `WebDDoS` labels.

Relevant options:

```text
--warmup SECONDS             default: 5
--duration SECONDS           default: 15
--cooldown SECONDS           default: 5
--source-host HOST           override the scenario source
--udp-pps PPS                default: 500, maximum: 10000
--syn-pps PPS                default: 250, maximum: 10000
--http-concurrency COUNT     default: 4, maximum: 32
--manifest-path PATH         default: data/experiments/EXPERIMENT_ID.json
--notes TEXT                 appended to ACTIVE-row notes
```

The driver uses `mnexec` to enter the selected Mininet host namespace. It
starts the generator in a new process group, sends that group SIGTERM at the
ACTIVE boundary, and escalates to SIGKILL after three seconds if necessary.
The `finally` path always publishes IDLE state and terminates the generator.

This driver creates validation or controlled collection traffic. It does not
train a model, run inference, assign labels from predictions, or claim attack
detection accuracy.
