#!/usr/bin/env python3
"""Run one bounded, explicitly labeled traffic scenario in Mininet."""

import argparse
import datetime
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid


STATE_VERSION = "sdn_experiment_state_v1"
STATUS_VERSION = "sdn_dataset_status_v1"
MANIFEST_VERSION = "sdn_traffic_experiment_v1"
SCENARIOS = ("BENIGN", "UDP_FLOOD", "TCP_SYN_LIKE", "HTTP_FLOOD")
EXPECTED_BRIDGES = {"s1", "s2", "s3", "s4"}
TARGET_IP = "10.0.0.100"
TARGET_HOST = "h_server"


def utc_timestamp(epoch=None):
    moment = (
        datetime.datetime.now(datetime.timezone.utc)
        if epoch is None
        else datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    )
    return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")


def atomic_write_json(path, payload):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".sdn-experiment-", dir=parent, text=True
    )
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
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


def find_binary(binary):
    result = subprocess.run(
        ["/bin/sh", "-c", "command -v -- \"$1\"", "sh", binary],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("required binary is unavailable: {}".format(binary))
    return result.stdout.strip()


def host_pid(host):
    result = subprocess.run(
        ["pgrep", "-f", "mininet:{}".format(host)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    pids = [int(value) for value in result.stdout.split() if value.isdigit()]
    live = []
    for pid in pids:
        try:
            with open("/proc/{}/cmdline".format(pid), "rb") as process:
                command_line = process.read().decode("utf-8", "replace")
            if "mininet:{}".format(host) in command_line:
                live.append(pid)
        except FileNotFoundError:
            continue
    if len(live) != 1:
        raise RuntimeError(
            "expected one Mininet process for {}, found {}".format(host, live)
        )
    return live[0]


def wait_for_readiness(status_path, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_reason = "status file has not appeared"
    while time.monotonic() < deadline:
        try:
            with open(status_path, encoding="utf-8") as status_file:
                status = json.load(status_file)
            age = time.time() - float(status["updated_at"])
            valid = (
                status.get("version") == STATUS_VERSION
                and status.get("ready") is True
                and status.get("datapaths") == 4
                and status.get("directed_links") == 12
                and float(status.get("stable_seconds", 0)) >= 5.0
                and -1.0 <= age <= 5.0
            )
            if valid:
                return status
            last_reason = "last status was {}".format(status)
        except (
            FileNotFoundError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            last_reason = str(exc)
        time.sleep(0.5)
    raise RuntimeError(
        "topology did not become recorder-ready within {}s: {}".format(
            timeout_seconds, last_reason
        )
    )


def verify_bridges(ovs_vsctl):
    result = subprocess.run(
        [ovs_vsctl, "list-br"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    bridges = set(result.stdout.split())
    if bridges != EXPECTED_BRIDGES:
        raise RuntimeError(
            "expected OVS bridges {}, found {}".format(
                sorted(EXPECTED_BRIDGES), sorted(bridges)
            )
        )
    return sorted(bridges)


def scenario_spec(args, binaries):
    if args.scenario == "BENIGN":
        source_host = args.source_host or "h1"
        attack_source_host = "none"
        script = (
            "while true; do "
            "{ping} -c 1 -W 1 {target} >/dev/null 2>&1; "
            "{curl} -fsS --max-time 2 -o /dev/null http://{target}/; "
            "sleep {interval}; "
            "done"
        ).format(
            ping=shlex.quote(binaries["ping"]),
            curl=shlex.quote(binaries["curl"]),
            target=TARGET_IP,
            interval=args.benign_interval,
        )
        command = [binaries["bash"], "-c", script]
        parameters = {
            "icmp_packets_per_cycle": 1,
            "http_requests_per_cycle": 1,
            "cycle_interval_seconds": args.benign_interval,
        }
    elif args.scenario == "UDP_FLOOD":
        source_host = args.source_host or "h2"
        attack_source_host = source_host
        interval_us = max(1, int(1000000 / args.udp_pps))
        command = [
            binaries["hping3"], "-2", "-n", "-q", "-i",
            "u{}".format(interval_us), "-p", str(args.udp_port), TARGET_IP,
        ]
        parameters = {
            "requested_packets_per_second": args.udp_pps,
            "hping_interval_microseconds": interval_us,
            "udp_destination_port": args.udp_port,
        }
    elif args.scenario == "TCP_SYN_LIKE":
        source_host = args.source_host or "h3"
        attack_source_host = source_host
        interval_us = max(1, int(1000000 / args.syn_pps))
        command = [
            binaries["hping3"], "-S", "-n", "-q", "-i",
            "u{}".format(interval_us), "-p", str(args.syn_port), TARGET_IP,
        ]
        parameters = {
            "requested_packets_per_second": args.syn_pps,
            "hping_interval_microseconds": interval_us,
            "tcp_destination_port": args.syn_port,
            "semantics": "synthetic repeated TCP SYN workload",
        }
    else:
        source_host = args.source_host or "h4"
        attack_source_host = source_host
        slots = " ".join(str(slot) for slot in range(args.http_concurrency))
        script = (
            "while true; do "
            "for slot in {slots}; do "
            "{curl} -fsS --max-time 3 -o /dev/null "
            "http://{target}/?slot=$slot & "
            "done; "
            "wait; "
            "done"
        ).format(
            slots=slots,
            curl=shlex.quote(binaries["curl"]),
            target=TARGET_IP,
        )
        command = [binaries["bash"], "-c", script]
        parameters = {
            "concurrency": args.http_concurrency,
            "request_timeout_seconds": 3,
        }
    return source_host, attack_source_host, command, parameters


def phase_state(
    phase,
    recording,
    experiment_id,
    scenario,
    attack_source_host,
    active_start,
    active_end,
    notes,
):
    return {
        "version": STATE_VERSION,
        "phase": phase,
        "recording": recording,
        "experiment_id": experiment_id,
        "scenario_label": scenario,
        "attack_source_host": attack_source_host,
        "active_start": active_start,
        "active_end": active_end,
        "notes": notes,
        "updated_at": time.time(),
    }


def terminate_process_group(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
    except ProcessLookupError:
        pass


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run one bounded scenario in an existing Mininet topology."
    )
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--experiment-id")
    parser.add_argument("--source-host", choices=("h1", "h2", "h3", "h4"))
    parser.add_argument("--warmup", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--cooldown", type=float, default=5.0)
    parser.add_argument("--readiness-timeout", type=float, default=90.0)
    parser.add_argument(
        "--state-path",
        default=os.environ.get(
            "SDN_DATASET_STATE_PATH", "/tmp/sdn_experiment_state.json"
        ),
    )
    parser.add_argument(
        "--status-path",
        default=os.environ.get(
            "SDN_DATASET_STATUS_PATH", "/tmp/sdn_dataset_status.json"
        ),
    )
    parser.add_argument(
        "--dataset-path", default=os.environ.get("SDN_DATASET_PATH", "")
    )
    parser.add_argument("--manifest-path")
    parser.add_argument("--notes", default="")
    parser.add_argument("--benign-interval", type=float, default=1.0)
    parser.add_argument("--udp-pps", type=int, default=500)
    parser.add_argument("--udp-port", type=int, default=9000)
    parser.add_argument("--syn-pps", type=int, default=250)
    parser.add_argument("--syn-port", type=int, default=80)
    parser.add_argument("--http-concurrency", type=int, default=4)
    parser.add_argument(
        "--lock-path", default="/tmp/sdn_traffic_experiment.lock"
    )
    args = parser.parse_args()

    for name in ("warmup", "duration", "cooldown"):
        if getattr(args, name) < 0:
            parser.error("--{} must be nonnegative".format(name))
    if args.duration <= 0:
        parser.error("--duration must be greater than zero")
    if not 1 <= args.udp_pps <= 10000:
        parser.error("--udp-pps must be between 1 and 10000")
    if not 1 <= args.syn_pps <= 10000:
        parser.error("--syn-pps must be between 1 and 10000")
    if not 1 <= args.http_concurrency <= 32:
        parser.error("--http-concurrency must be between 1 and 32")
    if args.benign_interval < 0.1:
        parser.error("--benign-interval must be at least 0.1")
    return args


def main():
    args = parse_args()
    if os.geteuid() != 0:
        raise RuntimeError("run the experiment driver as root for mnexec")

    binaries = {
        name: find_binary(name)
        for name in ("bash", "curl", "hping3", "mnexec", "ovs-vsctl", "ping")
    }
    source_host, attack_source_host, command, parameters = scenario_spec(
        args, binaries
    )
    experiment_id = args.experiment_id or "{}_{}_{}".format(
        args.scenario,
        datetime.datetime.now().strftime("%Y%m%dT%H%M%S"),
        uuid.uuid4().hex[:8],
    )
    manifest_path = args.manifest_path or os.path.join(
        "data", "experiments", "{}.json".format(experiment_id)
    )

    lock_parent = os.path.dirname(os.path.abspath(args.lock_path))
    os.makedirs(lock_parent, exist_ok=True)
    lock_file = open(args.lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise RuntimeError("another traffic experiment is already active") from exc

    readiness = wait_for_readiness(args.status_path, args.readiness_timeout)
    bridges = verify_bridges(binaries["ovs-vsctl"])
    namespace_pid = host_pid(source_host)

    start = time.time()
    active_start = start + args.warmup + 1.0
    active_end = active_start + args.duration
    cooldown_end = active_end + args.cooldown
    exact_command = shlex.join(command)
    namespace_command = shlex.join(
        [binaries["mnexec"], "-a", str(namespace_pid)] + command
    )
    manifest = {
        "version": MANIFEST_VERSION,
        "experiment_id": experiment_id,
        "scenario_label": args.scenario,
        "traffic_source_host": source_host,
        "attack_source_host": attack_source_host,
        "start_timestamp": utc_timestamp(start),
        "active_start_timestamp": utc_timestamp(active_start),
        "active_end_timestamp": utc_timestamp(active_end),
        "cooldown_end_timestamp": utc_timestamp(cooldown_end),
        "start_epoch": start,
        "active_start_epoch": active_start,
        "active_end_epoch": active_end,
        "cooldown_end_epoch": cooldown_end,
        "target_host": TARGET_HOST,
        "target_ip": TARGET_IP,
        "target": "{} ({})".format(TARGET_HOST, TARGET_IP),
        "duration_seconds": args.duration,
        "warmup_seconds": args.warmup,
        "cooldown_seconds": args.cooldown,
        "exact_command": exact_command,
        "namespace_command": namespace_command,
        "parameters": parameters,
        "dataset_path": args.dataset_path,
        "state_path": os.path.abspath(args.state_path),
        "status_path": os.path.abspath(args.status_path),
        "topology_readiness": readiness,
        "ovs_bridges": bridges,
        "status": "RUNNING",
    }
    atomic_write_json(manifest_path, manifest)
    print("experiment_id={}".format(experiment_id), flush=True)
    print("scenario_label={}".format(args.scenario), flush=True)
    print("source_host={}".format(source_host), flush=True)
    print("attack_source_host={}".format(attack_source_host), flush=True)
    print("target={} ({})".format(TARGET_HOST, TARGET_IP), flush=True)
    print("exact_command={}".format(exact_command), flush=True)

    process = None
    try:
        atomic_write_json(
            args.state_path,
            phase_state(
                "WARMUP", False, experiment_id, args.scenario,
                attack_source_host, active_start, active_end, args.notes,
            ),
        )
        time.sleep(args.warmup)

        atomic_write_json(
            args.state_path,
            phase_state(
                "ACTIVE", True, experiment_id, args.scenario,
                attack_source_host, active_start, active_end, args.notes,
            ),
        )
        delay = active_start - time.time()
        if delay > 0:
            time.sleep(delay)

        process = subprocess.Popen(
            [binaries["mnexec"], "-a", str(namespace_pid)] + command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        remaining = active_end - time.time()
        if remaining > 0:
            time.sleep(remaining)

        atomic_write_json(
            args.state_path,
            phase_state(
                "COOLDOWN", False, experiment_id, args.scenario,
                attack_source_host, active_start, active_end, args.notes,
            ),
        )
        terminate_process_group(process)
        process = None
        time.sleep(args.cooldown)

        manifest["status"] = "COMPLETE"
        manifest["completed_at"] = utc_timestamp()
        atomic_write_json(manifest_path, manifest)
        print("status=COMPLETE", flush=True)
        return 0
    except BaseException as exc:
        manifest["status"] = "FAILED"
        manifest["error"] = "{}: {}".format(type(exc).__name__, exc)
        manifest["completed_at"] = utc_timestamp()
        atomic_write_json(manifest_path, manifest)
        raise
    finally:
        terminate_process_group(process)
        atomic_write_json(
            args.state_path,
            phase_state(
                "IDLE", False, experiment_id, args.scenario,
                attack_source_host, active_start, active_end, args.notes,
            ),
        )
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("experiment interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print("experiment failed: {}".format(exc), file=sys.stderr)
        sys.exit(1)
