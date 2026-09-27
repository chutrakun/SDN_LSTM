#!/usr/bin/env python3
"""Plan or collect V3 runs using the existing lab, recorder, and topology API."""

import argparse
import csv
import fcntl
import json
import os
import signal
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

import traffic_experiment_driver as legacy
from v3_design import CLASSES, ROOT, TOPOLOGIES_ORDER, make_plan, write_plan
from topology.topology_config import public_profile

DEFAULT_PLAN = ROOT / "data/v3/plan_v1.json"
DEFAULT_DATASET = ROOT / "data/v3/windows_v1.csv"
DEFAULT_MANIFESTS = ROOT / "data/v3/manifests"
DEFAULT_LOGS = ROOT / "data/v3/logs"
DEFAULT_STATE = Path("/tmp/sdn_experiment_state.json")
DEFAULT_STATUS = Path("/tmp/sdn_dataset_status.json")
WORKER = ROOT / "experiments/v3_traffic_worker.py"


def api_json(base, route, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base.rstrip("/") + route, data=data,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=50 if body else 5) as response:
        return json.load(response)


def recorder_topology_preflight(entry):
    """Reject a plan whose expected shape differs from the authoritative profile."""
    profile = public_profile(entry["topology"])
    expected = entry["expected_topology"]
    if (expected.get("switches") != profile["switches"] or
            expected.get("directed_links") != profile["directed_links"]):
        raise RuntimeError("planned topology shape disagrees with %s profile" %
                           entry["topology"])


def require_topology(base, entry):
    state = api_json(base, "/api/topology/status")
    expected = entry["expected_topology"]
    if not (state.get("status") == "ready" and state.get("in_sync") is True
            and state.get("mininet_running") is True
            and state.get("selected_topology") == entry["topology"]
            and state.get("runtime_topology") == entry["topology"]
            and state.get("switches") == expected["switches"]
            and state.get("directed_links") == expected["directed_links"]):
        raise RuntimeError("backend topology is not ready for %s: %s" %
                           (entry["experiment_id"], state))
    return state


def require_recorder(status_path, entry):
    status = json.loads(status_path.read_text(encoding="utf-8"))
    expected = entry["expected_topology"]
    age = time.time() - float(status["updated_at"])
    if not (status.get("version") == legacy.STATUS_VERSION
            and status.get("ready") is True
            and status.get("datapaths") == expected["switches"]
            and status.get("directed_links") == expected["directed_links"]
            and status.get("stable_seconds", 0) >= 5
            and -1 <= age <= 5):
        raise RuntimeError("recorder is not ready for %s: %s" %
                           (entry["experiment_id"], status))
    return status


def verify_runtime_source(entry):
    expected_switches = {"s%d" % number for number in
                         range(1, entry["expected_topology"]["switches"] + 1)}
    bridges = set(subprocess.check_output(["ovs-vsctl", "list-br"], text=True).split())
    if bridges != expected_switches:
        raise RuntimeError("OVS bridges differ from selected topology")
    source = entry["source_facing"]
    value = subprocess.check_output(["ovs-vsctl", "get", "Interface",
                                     source["interface"], "ofport"], text=True).strip()
    if int(value) != source["port"]:
        raise RuntimeError("source-facing OVS ofport differs from topology-derived port")
    return {"bridges": sorted(bridges), "interface": source["interface"],
            "ofport": int(value)}


def worker_command(entry):
    spec = {key: entry[key] for key in ("scenario_label", "profile_behavior", "parameters")}
    return [sys.executable, str(WORKER), "--spec-json", json.dumps(spec, sort_keys=True)]


def row_counts(dataset_path, entry):
    if not dataset_path.exists():
        return {"source_rows": 0, "context_rows": 0}
    source = entry["source_facing"]
    source_rows = context_rows = 0
    with dataset_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["experiment_id"] != entry["experiment_id"]:
                continue
            if row["scenario_label"] != entry["scenario_label"]:
                raise RuntimeError("recorder scenario mismatch")
            if int(row["dpid"]) == source["dpid"] and int(row["port"]) == source["port"]:
                source_rows += 1
            else:
                context_rows += 1
    return {"source_rows": source_rows, "context_rows": context_rows}


def post_run_health(base):
    result = {}
    for diagnostic in ("pingall", "ping_server", "http_server"):
        try:
            result[diagnostic] = api_json(base, "/api/topology/diagnostics/" + diagnostic, {})
        except (OSError, ValueError) as exc:
            result[diagnostic] = {"error": str(exc)}
    result["topology"] = api_json(base, "/api/topology/status")
    return result



def stop_own_group(process):
    """Stop only a process group this runner started with start_new_session."""
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def run_one(entry, args):
    if os.geteuid() != 0:
        raise RuntimeError("run-one requires root for mnexec and OVS inspection")
    recorder_topology_preflight(entry)
    manifest_path = args.manifests / (entry["experiment_id"] + ".json")
    if manifest_path.exists():
        raise FileExistsError("refusing to replace manifest: " + str(manifest_path))
    if args.dataset.exists():
        with args.dataset.open(newline="", encoding="utf-8") as handle:
            if any(row["experiment_id"] == entry["experiment_id"] for row in csv.DictReader(handle)):
                raise FileExistsError("dataset already contains experiment: " + entry["experiment_id"])
    topology_before = require_topology(args.backend, entry)
    recorder_before = require_recorder(args.status_path, entry)
    source_check = verify_runtime_source(entry)
    source_pid = legacy.host_pid(entry["traffic_source_host"])
    sink_needed = entry["scenario_label"] == "UDP_FLOOD" or (
        entry["scenario_label"] == "BENIGN" and
        entry["profile_behavior"] in ("low_udp", "idle_bursty_mixed"))
    server_pid = legacy.host_pid("h_server") if sink_needed else None
    mnexec = legacy.find_binary("mnexec")
    command = worker_command(entry)
    namespace_command = [mnexec, "-a", str(source_pid)] + command
    sink_command = ([mnexec, "-a", str(server_pid), sys.executable, str(WORKER),
                     "--udp-sink", "--duration",
                     str(entry["parameters"]["duration_seconds"] + 5)] if sink_needed else None)
    args.manifests.mkdir(parents=True, exist_ok=True)
    args.logs.mkdir(parents=True, exist_ok=True)
    log_path = args.logs / (entry["experiment_id"] + ".log")
    start = time.time()
    active_start = start + args.warmup + 1
    active_end = active_start + entry["parameters"]["duration_seconds"]
    manifest = dict(entry)
    manifest.update({
        "version": "sdn_dataset_v3_manifest_v1", "status": "RUNNING",
        "target_host": "h_server", "target_ip": "10.0.0.100",
        "attack_source_host": "none" if entry["scenario_label"] == "BENIGN" else entry["traffic_source_host"],
        "start_epoch": start, "start_timestamp": legacy.utc_timestamp(start),
        "active_start_epoch": active_start, "active_start_timestamp": legacy.utc_timestamp(active_start),
        "active_end_epoch": active_end, "active_end_timestamp": legacy.utc_timestamp(active_end),
        "warmup_seconds": args.warmup, "cooldown_seconds": args.cooldown,
        "dataset_path": str(args.dataset), "log_path": str(log_path),
        "state_path": str(args.state_path), "status_path": str(args.status_path),
        "exact_command": shlex.join(command), "namespace_command": shlex.join(namespace_command),
        "udp_sink_namespace_command": shlex.join(sink_command) if sink_command else None,
        "topology_before": topology_before, "recorder_before": recorder_before,
        "runtime_source_port_check": source_check,
    })
    legacy.atomic_write_json(str(manifest_path), manifest)
    worker = sink = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            legacy.atomic_write_json(str(args.state_path), legacy.phase_state(
                "WARMUP", False, entry["experiment_id"], entry["scenario_label"],
                manifest["attack_source_host"], active_start, active_end,
                "v3 profile=%s topology=%s host=%s" %
                (entry["profile_id"], entry["topology"], entry["traffic_source_host"])))
            time.sleep(args.warmup)
            legacy.atomic_write_json(str(args.state_path), legacy.phase_state(
                "ACTIVE", True, entry["experiment_id"], entry["scenario_label"],
                manifest["attack_source_host"], active_start, active_end,
                "v3 profile=%s topology=%s host=%s" %
                (entry["profile_id"], entry["topology"], entry["traffic_source_host"])))
            if sink_command:
                sink = subprocess.Popen(sink_command, stdout=log, stderr=log,
                                        start_new_session=True)
                time.sleep(.25)
                if sink.poll() is not None:
                    raise RuntimeError("UDP sink failed to start; see run log")
            delay = active_start - time.time()
            if delay > 0:
                time.sleep(delay)
            worker = subprocess.Popen(namespace_command, stdout=log, stderr=log,
                                      start_new_session=True)
            remaining = active_end - time.time()
            if remaining > 0:
                time.sleep(remaining)
            legacy.atomic_write_json(str(args.state_path), legacy.phase_state(
                "COOLDOWN", False, entry["experiment_id"], entry["scenario_label"],
                manifest["attack_source_host"], active_start, active_end, "v3"))
            worker_code = worker.poll()
            stop_own_group(worker)
            worker = None
            if worker_code not in (None, 0):
                raise RuntimeError("traffic worker exited early with code %s" % worker_code)
            stop_own_group(sink)
            sink = None
            time.sleep(args.cooldown)
        deadline = time.monotonic() + 8
        counts = row_counts(args.dataset, entry)
        while counts["source_rows"] < 5 and time.monotonic() < deadline:
            time.sleep(1)
            counts = row_counts(args.dataset, entry)
        manifest["recorded_windows"] = counts
        if counts["source_rows"] < 5:
            raise RuntimeError("fewer than five source-facing windows were recorded")
        manifest["post_run_health"] = post_run_health(args.backend)
        health = manifest["post_run_health"]
        health_ok = (
            health["topology"].get("status") == "ready"
            and health["topology"].get("in_sync") is True
            and health["pingall"].get("ok") is True
            and float(health["pingall"].get("packet_loss_percent", 100)) == 0
            and health["ping_server"].get("ok") is True
            and health["http_server"].get("ok") is True
        )
        manifest["post_run_health_ok"] = health_ok
        if not health_ok:
            raise RuntimeError("post-run Mininet health check failed")
        manifest["status"] = "COMPLETE"
        manifest["completed_at"] = legacy.utc_timestamp()
        legacy.atomic_write_json(str(manifest_path), manifest)
        return manifest
    except BaseException as exc:
        manifest["status"] = "FAILED"
        manifest["error"] = "%s: %s" % (type(exc).__name__, exc)
        manifest["completed_at"] = legacy.utc_timestamp()
        legacy.atomic_write_json(str(manifest_path), manifest)
        raise
    finally:
        stop_own_group(worker)
        stop_own_group(sink)
        legacy.atomic_write_json(str(args.state_path), legacy.phase_state(
            "IDLE", False, entry["experiment_id"], entry["scenario_label"],
            manifest["attack_source_host"], active_start, active_end, "v3"))
        if "post_run_health" not in manifest:
            try:
                manifest["post_run_health"] = post_run_health(args.backend)
            except (OSError, ValueError) as health_error:
                manifest["post_run_health"] = {"error": str(health_error)}
            manifest["post_run_health_ok"] = False
            legacy.atomic_write_json(str(manifest_path), manifest)



def locked_run_one(entry, args):
    """Share the original driver's lock so V1/V3 states cannot overlap."""
    with open("/tmp/sdn_traffic_experiment.lock", "a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another traffic experiment is active") from exc
        try:
            return run_one(entry, args)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def wait_topology(base, entry, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return require_topology(base, entry)
        except (OSError, RuntimeError, ValueError):
            time.sleep(1)
    raise RuntimeError("topology did not become ready: " + entry["topology"])


def wait_recorder(status_path, entry, timeout=30):
    """Allow the recorder its stable interval and one complete polling window."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return require_recorder(status_path, entry)
        except (OSError, RuntimeError, ValueError, KeyError):
            time.sleep(1)
    raise RuntimeError("recorder did not become ready: " + entry["topology"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    planning = sub.add_parser("plan")
    planning.add_argument("--output", type=Path, default=DEFAULT_PLAN)
    for name in ("run-one", "run-plan", "run-smoke"):
        command = sub.add_parser(name)
        command.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
        command.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
        command.add_argument("--manifests", type=Path, default=DEFAULT_MANIFESTS)
        command.add_argument("--logs", type=Path, default=DEFAULT_LOGS)
        command.add_argument("--state-path", type=Path, default=DEFAULT_STATE)
        command.add_argument("--status-path", type=Path, default=DEFAULT_STATUS)
        command.add_argument("--backend", default="http://127.0.0.1:5000")
        command.add_argument("--warmup", type=float, default=5)
        command.add_argument("--cooldown", type=float, default=5)
    one = sub.choices["run-one"]
    one.add_argument("experiment_id")
    for mode in ("run-plan", "run-smoke"):
        sub.choices[mode].add_argument("--allow-topology-apply", action="store_true")
        sub.choices[mode].add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "plan":
        plan = write_plan(args.output)
        print("planned_experiments=%s path=%s" % (len(plan["experiments"]), args.output))
        return
    if args.warmup < 0 or args.cooldown < 0:
        parser.error("warmup/cooldown must be nonnegative")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    expected = make_plan()
    if plan != expected:
        raise ValueError("plan does not match deterministic V3 design")
    if args.command == "run-one":
        matches = [entry for entry in plan["experiments"] if entry["experiment_id"] == args.experiment_id]
        if len(matches) != 1:
            raise ValueError("experiment ID absent or ambiguous")
        print(json.dumps(locked_run_one(matches[0], args), indent=2))
        return
    if not (args.execute and args.allow_topology_apply):
        parser.error(args.command + " requires --execute and --allow-topology-apply")
    selected = (plan["experiments"] if args.command == "run-plan" else
                [next(entry for entry in plan["experiments"] if entry["experiment_id"] == experiment_id)
                 for experiment_id in plan["smoke_experiment_ids"]])
    # Validate collection capability and output locations before any topology API mutation.
    selected_ids = {entry["experiment_id"] for entry in selected}
    for entry in selected:
        if (args.manifests / (entry["experiment_id"] + ".json")).exists():
            raise FileExistsError("manifest already exists: " + entry["experiment_id"])
    if args.dataset.exists():
        with args.dataset.open(newline="", encoding="utf-8") as handle:
            recorded_ids = {row["experiment_id"] for row in csv.DictReader(handle)}
        if recorded_ids & selected_ids:
            raise FileExistsError("dataset already contains planned experiment IDs")
    for topology in {entry["topology"] for entry in selected}:
        recorder_topology_preflight(next(entry for entry in selected
                                         if entry["topology"] == topology))
    current_topology = None
    for entry in selected:
        if entry["topology"] != current_topology:
            current = api_json(args.backend, "/api/topology/status")
            if current.get("selected_topology") != entry["topology"] or current.get("status") != "ready":
                api_json(args.backend, "/api/topology/apply", {"topology": entry["topology"]})
            wait_topology(args.backend, entry)
            wait_recorder(args.status_path, entry)
            current_topology = entry["topology"]
        locked_run_one(entry, args)


if __name__ == "__main__":
    main()
