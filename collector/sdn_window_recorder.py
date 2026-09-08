"""Opt-in CSV recorder for controller port-stat polling windows."""

import atexit
import csv
import json
import logging
import os
import queue
import tempfile
import threading
import time


SCHEMA_VERSION = "sdn_window_v1"
EXPERIMENT_STATE_VERSION = "sdn_experiment_state_v1"
STATUS_VERSION = "sdn_dataset_status_v1"

CSV_COLUMNS = (
    "schema_version",
    "experiment_id",
    "scenario_label",
    "attack_source_host",
    "notes",
    "window_start",
    "window_end",
    "dpid",
    "port",
    "interval_seconds",
    "rx_packets_delta",
    "tx_packets_delta",
    "rx_bytes_delta",
    "tx_bytes_delta",
    "rx_pps",
    "tx_pps",
    "rx_bytes_per_sec",
    "tx_bytes_per_sec",
    "last_protocol",
    "last_dst_port",
    "last_source_ip",
)

NON_NEGATIVE_FIELDS = (
    "interval_seconds",
    "rx_packets_delta",
    "tx_packets_delta",
    "rx_bytes_delta",
    "tx_bytes_delta",
    "rx_pps",
    "tx_pps",
    "rx_bytes_per_sec",
    "tx_bytes_per_sec",
)


def _enabled_from_environment():
    value = os.environ.get("SDN_DATASET_ENABLED", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


class SdnWindowCsvRecorder:
    """Queue polling-window rows for a lightweight background CSV writer."""

    def __init__(
        self,
        enabled=False,
        path=None,
        experiment_id="",
        scenario_label="",
        attack_source_host="",
        notes="",
        logger=None,
        state_path=None,
        status_path=None,
        queue_size=4096,
    ):
        self.enabled = enabled
        self.path = path
        self.experiment_id = experiment_id
        self.scenario_label = scenario_label
        self.attack_source_host = attack_source_host
        self.notes = notes
        self.log = logger or logging.getLogger("sdn.dataset")
        self.state_path = state_path
        self.status_path = status_path
        self._queue = None
        self._thread = None
        self._stop_marker = object()
        self._failed = False
        self._last_window_end = {}
        self._lock = threading.Lock()
        self._last_full_warning = 0.0

        self._state_lock = threading.Lock()
        self._active_state = None
        self._topology_status = {
            "version": STATUS_VERSION,
            "updated_at": time.time(),
            "ready": False,
            "datapaths": 0,
            "directed_links": 0,
            "stable_seconds": 0.0,
        }
        self._control_stop = threading.Event()
        self._control_thread = None
        self._last_state_warning = 0.0
        self._last_status_warning = 0.0

        if not self.enabled:
            return

        if (
            not self.state_path
            and (not self.experiment_id or not self.scenario_label)
        ):
            self.log.error(
                "SDN dataset recording disabled: experiment_id and "
                "scenario_label are required"
            )
            self.enabled = False
            return

        self._queue = queue.Queue(maxsize=queue_size)
        self._thread = threading.Thread(
            target=self._writer_loop,
            name="sdn-window-csv-writer",
            daemon=True,
        )
        self._thread.start()
        if self.state_path or self.status_path:
            self._control_thread = threading.Thread(
                target=self._control_loop,
                name="sdn-dataset-control",
                daemon=True,
            )
            self._control_thread.start()
        atexit.register(self.close)

        self.log.info(
            "SDN dataset recording enabled: schema=%s path=%s "
            "experiment_id=%s scenario_label=%s",
            SCHEMA_VERSION,
            self.path,
            self.experiment_id,
            self.scenario_label,
        )

    @classmethod
    def from_environment(cls, logger=None):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_path = os.path.join(
            project_root,
            "data",
            "sdn_window_dataset.csv",
        )
        return cls(
            enabled=_enabled_from_environment(),
            path=os.environ.get("SDN_DATASET_PATH", default_path),
            experiment_id=os.environ.get("SDN_EXPERIMENT_ID", "").strip(),
            scenario_label=os.environ.get("SDN_SCENARIO_LABEL", "").strip(),
            attack_source_host=os.environ.get(
                "SDN_ATTACK_SOURCE_HOST",
                "",
            ).strip(),
            notes=os.environ.get("SDN_DATASET_NOTES", "").strip(),
            logger=logger,
            state_path=os.environ.get(
                "SDN_DATASET_STATE_PATH",
                "",
            ).strip() or None,
            status_path=os.environ.get(
                "SDN_DATASET_STATUS_PATH",
                "",
            ).strip() or None,
        )

    def enqueue(self, measurement):
        """Nonblocking enqueue; return True only when a row is accepted."""
        if not self.enabled or self._failed:
            return False

        metadata = self._metadata_for_window(measurement)
        if metadata is None:
            return False

        if any(measurement[field] < 0 for field in NON_NEGATIVE_FIELDS):
            self.log.warning(
                "Dataset window skipped after counter reset: s%s:%s "
                "window_end=%s",
                measurement.get("dpid"),
                measurement.get("port"),
                measurement.get("window_end"),
            )
            return False

        row = metadata
        row.update(measurement)

        key = (measurement["dpid"], measurement["port"])
        window_end = measurement["window_end"]

        with self._lock:
            previous_end = self._last_window_end.get(key)
            if previous_end is not None and window_end <= previous_end:
                self.log.debug(
                    "Duplicate dataset window skipped: s%s:%s window_end=%s",
                    key[0],
                    key[1],
                    window_end,
                )
                return False

            try:
                self._queue.put_nowait(row)
            except queue.Full:
                now = time.monotonic()
                if now - self._last_full_warning >= 30:
                    self.log.warning(
                        "SDN dataset queue full; polling windows are being dropped"
                    )
                    self._last_full_warning = now
                return False

            self._last_window_end[key] = window_end

        return True

    def _metadata_for_window(self, measurement):
        if not self.state_path:
            return {
                "schema_version": SCHEMA_VERSION,
                "experiment_id": self.experiment_id,
                "scenario_label": self.scenario_label,
                "attack_source_host": self.attack_source_host,
                "notes": self.notes,
            }

        with self._state_lock:
            state = dict(self._active_state) if self._active_state else None

        if state is None:
            return None

        window_start = measurement["window_start"]
        window_end = measurement["window_end"]
        if (
            window_start < state["active_start"]
            or window_end > state["active_end"]
        ):
            return None

        notes = state.get("notes", "")
        phase_note = "phase=ACTIVE"
        notes = "{}; {}".format(phase_note, notes) if notes else phase_note
        return {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": state["experiment_id"],
            "scenario_label": state["scenario_label"],
            "attack_source_host": state["attack_source_host"],
            "notes": notes,
        }

    def update_topology_status(
        self,
        ready,
        datapaths,
        directed_links,
        stable_seconds,
    ):
        """Publish an in-memory readiness snapshot for the control thread."""
        if not self.enabled or not self.status_path:
            return

        status = {
            "version": STATUS_VERSION,
            "updated_at": time.time(),
            "ready": bool(ready),
            "datapaths": int(datapaths),
            "directed_links": int(directed_links),
            "stable_seconds": float(stable_seconds),
        }
        with self._state_lock:
            self._topology_status = status

    def _control_loop(self):
        next_status_write = 0.0
        while not self._control_stop.wait(0.25):
            if self.state_path:
                self._refresh_experiment_state()

            now = time.monotonic()
            if self.status_path and now >= next_status_write:
                with self._state_lock:
                    status = dict(self._topology_status)
                status["updated_at"] = time.time()
                try:
                    self._atomic_write_json(self.status_path, status)
                except Exception as exc:
                    if now - self._last_status_warning >= 30:
                        self.log.warning(
                            "Dataset readiness status write failed: %s",
                            exc,
                        )
                        self._last_status_warning = now
                next_status_write = now + 1.0

    def _refresh_experiment_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as state_file:
                state = json.load(state_file)
        except FileNotFoundError:
            state = None
        except Exception as exc:
            now = time.monotonic()
            if now - self._last_state_warning >= 30:
                self.log.warning(
                    "Experiment state unreadable; recording paused: %s",
                    exc,
                )
                self._last_state_warning = now
            state = None

        active_state = None
        if state and state.get("recording") is True:
            try:
                candidate = {
                    "experiment_id": str(state["experiment_id"]).strip(),
                    "scenario_label": str(state["scenario_label"]).strip(),
                    "attack_source_host": str(
                        state["attack_source_host"]
                    ).strip(),
                    "notes": str(state.get("notes", "")).strip(),
                    "active_start": float(state["active_start"]),
                    "active_end": float(state["active_end"]),
                }
                valid = (
                    state.get("version") == EXPERIMENT_STATE_VERSION
                    and state.get("phase") == "ACTIVE"
                    and candidate["experiment_id"]
                    and candidate["scenario_label"]
                    and candidate["attack_source_host"]
                    and candidate["active_start"] < candidate["active_end"]
                )
                if valid:
                    active_state = candidate
            except (KeyError, TypeError, ValueError):
                active_state = None

        with self._state_lock:
            self._active_state = active_state

    @staticmethod
    def _atomic_write_json(path, payload):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".sdn-state-",
            dir=parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, path)
        except Exception:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            raise

    def _writer_loop(self):
        try:
            parent = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(parent, exist_ok=True)

            has_content = os.path.exists(self.path) and os.path.getsize(self.path) > 0
            if has_content:
                with open(self.path, newline="", encoding="utf-8") as existing:
                    header = next(csv.reader(existing), None)
                if header != list(CSV_COLUMNS):
                    raise ValueError(
                        "existing dataset header does not match sdn_window_v1"
                    )

            with open(self.path, "a", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
                if not has_content:
                    writer.writeheader()
                    output.flush()

                pending = 0
                last_flush = time.monotonic()

                while True:
                    try:
                        row = self._queue.get(timeout=1.0)
                    except queue.Empty:
                        row = None

                    if row is self._stop_marker:
                        break

                    if row is not None:
                        writer.writerow(row)
                        pending += 1

                    now = time.monotonic()
                    if pending and (pending >= 64 or now - last_flush >= 1.0):
                        output.flush()
                        pending = 0
                        last_flush = now

                output.flush()

        except Exception:
            self._failed = True
            self.log.exception(
                "SDN dataset writer failed; controller operation will continue"
            )

    def close(self):
        self._control_stop.set()
        if self._control_thread and self._control_thread.is_alive():
            self._control_thread.join(timeout=2)

        if not self.enabled or not self._thread or not self._thread.is_alive():
            return
        try:
            self._queue.put_nowait(self._stop_marker)
        except queue.Full:
            return
        self._thread.join(timeout=3)
