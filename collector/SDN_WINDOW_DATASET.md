# SDN time-window dataset recorder

The controller can write its existing OpenFlow port-stat polling measurements
to a CSV file. Recording is disabled by default and does not alter forwarding,
detection, model inference, thresholds, or mitigation.

Enable it only for a controlled experiment:

```bash
export SDN_DATASET_ENABLED=1
export SDN_DATASET_PATH=/path/to/experiment.csv
export SDN_EXPERIMENT_ID=experiment-001
export SDN_SCENARIO_LABEL=BENIGN
export SDN_ATTACK_SOURCE_HOST=none
export SDN_DATASET_NOTES="optional phase or experiment notes"
```
`SDN_EXPERIMENT_ID` and `SDN_SCENARIO_LABEL` are required in fixed-metadata
mode. The sequential experiment interface below supplies them at runtime.
Labels are explicit experiment metadata; model predictions never set or change
them. If `SDN_DATASET_PATH` is omitted, the enabled recorder uses
`data/sdn_window_dataset.csv`.

One `sdn_window_v1` row represents the counter change for one `(dpid, port)`
between two consecutive OpenFlow port-stat replies. `window_start` and
`window_end` are Unix timestamps in seconds, and `interval_seconds` is their
unrounded difference. Packet rates are packets/second. Byte rates are
bytes/second; they are not converted to bits/second.

The candidate training measurements are the packet and byte counter deltas,
their per-second rates, the polling interval, and the last-seen protocol and
destination port context. `last_source_ip` is audit metadata. Protocol,
destination port, and source IP can be empty and are last-seen PacketIn context,
not a summary of every packet in the polling window.

Rows begin only after the controller observes four switches, twelve directed
links, and a complete polling interval after the topology stability window.
Counter-reset windows with negative values are skipped. Enqueueing is
nonblocking; a bounded queue feeds a background writer that flushes periodically.

This is an SDN switch-port time-window dataset. It is not CICIDS flow-level
data, and existing CICIDS artifacts are neither read nor replaced by the
recorder.

## Sequential experiment metadata

For sequential scenarios under one controller, use the atomic runtime state
interface:

```bash
export SDN_DATASET_STATE_PATH=/tmp/sdn_experiment_state.json
export SDN_DATASET_STATUS_PATH=/tmp/sdn_dataset_status.json
```

The Phase 2G traffic driver writes explicit metadata to the state path. In this
mode, only complete polling windows within a valid ACTIVE interval are recorded.
Missing, malformed, inactive, or expired state fails closed by pausing rows.
The status path reports topology readiness without adding disk I/O to the stats
handler.
