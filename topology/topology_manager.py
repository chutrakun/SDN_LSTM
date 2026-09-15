"""Backend-owned Mininet lifecycle and desired/runtime topology state."""

import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from topology.topology_config import (
    DEFAULT_CONFIG_PATH,
    TOPOLOGIES,
    expected_directed_edges,
    load_topology_config,
    normalize_topology_id,
    public_profile,
    supported_profiles,
    write_topology_config,
)


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(Path(PROJECT_ROOT) / '.env')
TOPOLOGY_SCRIPT = os.path.join(PROJECT_ROOT, "topology", "network_topology.py")
PYTHON_BIN = os.environ.get(
    "SDN_MININET_PYTHON",
    os.path.expanduser("~/.pyenv/versions/sdn-env38/bin/python"),
)
PID_PATH = "/tmp/anti_sdn_topology.pid"
LOG_PATH = "/tmp/anti_sdn_mininet.log"
CONTROL_SOCKET = "/tmp/anti_sdn_topology.sock"
RYU_HOST = os.environ.get("RYU_HOST", "127.0.0.1")
RYU_PORT = int(os.environ.get("RYU_PORT", "6653"))
RUNTIME_STALE_SECONDS = 15
READINESS_TIMEOUT_SECONDS = 75


class TopologyBusyError(RuntimeError):
    pass


class TopologyManager:
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        self.config_path = os.path.abspath(config_path)
        config, fallback = load_topology_config(self.config_path)
        self._lock = threading.RLock()
        self._changing = False
        self._selected = config["topology"]
        self._runtime_report = None
        self._status = "offline"
        self._message = fallback or "Waiting for Ryu topology report"
        self._error = None

    def _pid_from_file(self):
        try:
            with open(PID_PATH) as handle:
                return int(handle.read().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _pid_alive(pid):
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _pid_command(pid):
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as handle:
                return handle.read().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            return ""

    def _pid_is_topology(self, pid):
        return self._pid_alive(pid) and TOPOLOGY_SCRIPT in self._pid_command(pid)

    def _write_pid(self, pid):
        directory = os.path.dirname(PID_PATH)
        fd, temporary = tempfile.mkstemp(prefix=".anti_sdn_topology.", dir=directory)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write("%s\n" % pid)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, PID_PATH)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @staticmethod
    def _ryu_available(timeout=0.5):
        """Check LISTEN state without opening an invalid OpenFlow connection."""
        del timeout
        expected_port = "%04X" % RYU_PORT
        for table in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                with open(table) as handle:
                    next(handle, None)
                    for line in handle:
                        fields = line.split()
                        if len(fields) > 3 and fields[1].rsplit(":", 1)[-1] == expected_port and fields[3] == "0A":
                            return True
            except OSError:
                continue
        return False

    def _classify_runtime(self, switches, links):
        switch_set = set(switches)
        link_set = set(links)
        for topology_id, profile in TOPOLOGIES.items():
            expected_switches = {int(name[1:]) for name in profile["switches"]}
            if switch_set == expected_switches and link_set == expected_directed_edges(topology_id):
                return topology_id
        return None

    def record_runtime(self, payload):
        try:
            switches = sorted({int(value) for value in payload.get("switches", [])})
            links = sorted({(int(edge[0]), int(edge[1])) for edge in payload.get("links", [])})
            stable_seconds = max(0.0, float(payload.get("stable_seconds", 0.0)))
        except (TypeError, ValueError, IndexError):
            raise ValueError("invalid Ryu topology report")

        now = time.time()
        runtime_topology = self._classify_runtime(switches, links)
        with self._lock:
            self._runtime_report = {
                "received_at": now,
                "reported_at": payload.get("reported_at"),
                "switches": switches,
                "links": links,
                "stable_seconds": stable_seconds,
                "runtime_topology": runtime_topology,
            }
            in_sync = runtime_topology == self._selected and stable_seconds >= 5.0
            if in_sync:
                self._status = "ready"
                self._message = "%s topology is running and stable" % self._selected
                self._error = None
            elif not self._changing:
                self._status = "changing"
                self._message = "Ryu topology does not yet match the persisted selection"
            return self.status()

    def _snapshot_locked(self):
        config, fallback = load_topology_config(self.config_path)
        self._selected = config["topology"]
        expected = public_profile(self._selected)
        report = self._runtime_report
        stale = not report or time.time() - report["received_at"] > RUNTIME_STALE_SECONDS
        if stale:
            if self._changing:
                status = "changing"
            elif self._status == "error":
                status = "error"
            else:
                status = "offline"
            runtime_topology = None
            switch_count = 0
            directed_link_count = 0
            stable_seconds = 0.0
            in_sync = False
        else:
            runtime_topology = report["runtime_topology"]
            switch_count = len(report["switches"])
            directed_link_count = len(report["links"])
            stable_seconds = report["stable_seconds"]
            in_sync = runtime_topology == self._selected and stable_seconds >= 5.0
            status = "ready" if in_sync else ("changing" if self._changing or self._status != "error" else "error")
        if fallback:
            self._message = fallback
        state = "restarting" if status == "changing" else status
        return {
            "selected_topology": self._selected,
            "runtime_topology": runtime_topology,
            "status": status,
            "state": state,
            "topology": self._selected,
            "switches": switch_count,
            "directed_links": directed_link_count,
            "expected_switches": expected["switches"],
            "expected_directed_links": expected["directed_links"],
            "in_sync": in_sync,
            "topology_stable_seconds": stable_seconds,
            "ryu_available": self._ryu_available(),
            "mininet_running": self._pid_alive(self._pid_from_file()),
            "message": self._message,
            "error": self._error,
            "config_version": config["version"],
            "updated_at": config["updated_at"],
            "supported_topologies": supported_profiles(),
        }

    def status(self):
        with self._lock:
            return self._snapshot_locked()

    def apply(self, topology_id):
        topology_id = normalize_topology_id(topology_id)
        with self._lock:
            if self._changing:
                raise TopologyBusyError("topology change already in progress")
            config = write_topology_config(topology_id, self.config_path)
            self._selected = topology_id
            self._changing = True
            self._status = "changing"
            self._message = "Persisted %s; stopping old Mininet" % topology_id
            self._error = None
            self._runtime_report = None
            worker = threading.Thread(target=self._change_worker, args=(topology_id,), daemon=True)
            worker.start()
            result = self._snapshot_locked()
            result["accepted"] = True
            result["persisted_config"] = config
            return result

    def _known_topology_pids(self):
        pids = set()
        pid = self._pid_from_file()
        if self._pid_is_topology(pid):
            pids.add(pid)
        try:
            result = subprocess.run(
                ["pgrep", "-f", TOPOLOGY_SCRIPT], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
            )
            for value in result.stdout.split():
                candidate = int(value)
                if self._pid_is_topology(candidate):
                    pids.add(candidate)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return sorted(pids)

    def _owned_mininet_descendants(self, roots):
        """Return exact Mininet shell PIDs proven to descend from our runtime."""
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,ppid="], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        children = {}
        for line in result.stdout.splitlines():
            try:
                pid, parent = (int(value) for value in line.split())
            except (TypeError, ValueError):
                continue
            children.setdefault(parent, []).append(pid)
        descendants = set()
        pending = list(roots)
        while pending:
            for child in children.get(pending.pop(), []):
                if child not in descendants:
                    descendants.add(child)
                    pending.append(child)
        return sorted(
            pid for pid in descendants
            if "mininet:" in self._pid_command(pid)
        )

    @staticmethod
    def _bridge_exists(bridge):
        try:
            return subprocess.run(
                ["sudo", "-n", "ovs-vsctl", "br-exists", bridge],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _bridge_owned_by_project(bridge):
        """Recognize only this demo's named OpenFlow bridge signature."""
        try:
            controller = subprocess.run(
                ["sudo", "-n", "ovs-vsctl", "get-controller", bridge],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=5,
            )
            ports = subprocess.run(
                ["sudo", "-n", "ovs-vsctl", "list-ports", bridge],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        controllers = {
            value.strip().strip('"') for value in controller.stdout.splitlines()
            if value.strip()
        }
        port_names = [value.strip() for value in ports.stdout.splitlines() if value.strip()]
        return (
            controller.returncode == 0
            and ports.returncode == 0
            and controllers == {"tcp:%s:%s" % (RYU_HOST, RYU_PORT)}
            and all(name.startswith(bridge + "-eth") for name in port_names)
        )

    def _stop_mininet(self):
        topology_pids = self._known_topology_pids()
        owned_host_pids = self._owned_mininet_descendants(topology_pids)
        for pid in topology_pids:
            subprocess.run(
                ["sudo", "-n", "kill", "-TERM", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
        deadline = time.time() + 8
        while time.time() < deadline and any(self._pid_alive(pid) for pid in self._known_topology_pids()):
            time.sleep(0.25)
        for pid in self._known_topology_pids():
            subprocess.run(
                ["sudo", "-n", "kill", "-KILL", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
        for pid in owned_host_pids:
            if self._pid_alive(pid) and "mininet:" in self._pid_command(pid):
                subprocess.run(
                    ["sudo", "-n", "kill", "-TERM", str(pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                )
        try:
            os.unlink(PID_PATH)
        except OSError:
            pass
        try:
            os.unlink(CONTROL_SOCKET)
        except OSError:
            pass
        # `mn -c` is intentionally not used here: this Mininet release kills
        # every ryu-manager process. Clean only this project's known runtime.
        known_switches = sorted(
            {name for profile in TOPOLOGIES.values() for name in profile["switches"]}
        )
        owned_bridges = []
        for bridge in known_switches:
            if not self._bridge_exists(bridge):
                continue
            if not self._bridge_owned_by_project(bridge):
                raise RuntimeError(
                    "refusing to remove bridge %s: project ownership is uncertain" % bridge
                )
            owned_bridges.append(bridge)
            subprocess.run(
                ["sudo", "-n", "ovs-vsctl", "--if-exists", "del-br", bridge],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
        try:
            links = subprocess.run(
                ["ip", "-o", "link", "show"], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
            ).stdout
            for line in links.splitlines():
                interface = line.split(": ", 1)[1].split("@", 1)[0]
                if (
                    "-eth" in interface
                    and interface.split("-eth", 1)[0] in owned_bridges
                ):
                    subprocess.run(
                        ["sudo", "-n", "ip", "link", "delete", interface],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                    )
        except (OSError, IndexError, subprocess.TimeoutExpired):
            pass

    def _start_mininet(self):
        if not os.path.isfile(PYTHON_BIN) or not os.access(PYTHON_BIN, os.X_OK):
            raise RuntimeError(
                "Mininet interpreter is unavailable: %s; set SDN_MININET_PYTHON "
                "or run scripts/setup.sh" % PYTHON_BIN
            )
        log_handle = open(LOG_PATH, "w")
        try:
            process = subprocess.Popen(
                [
                    "sudo", "-n", PYTHON_BIN, TOPOLOGY_SCRIPT,
                    "--background", "--config", self.config_path,
                    "--control-socket", CONTROL_SOCKET,
                    "--controller-host", RYU_HOST,
                    "--controller-port", str(RYU_PORT),
                ],
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        self._write_pid(process.pid)
        time.sleep(2)
        if process.poll() is not None:
            try:
                with open(LOG_PATH) as handle:
                    detail = handle.read()[-800:]
            except OSError:
                detail = "no Mininet log available"
            raise RuntimeError("Mininet startup failed: %s" % detail)
        return process

    def _change_worker(self, topology_id):
        try:
            with self._lock:
                self._message = "Stopping old Mininet and cleaning stale interfaces"
            self._stop_mininet()
            with self._lock:
                self._message = "Waiting for Ryu on %s:%s" % (RYU_HOST, RYU_PORT)
            deadline = time.time() + 30
            while time.time() < deadline and not self._ryu_available():
                time.sleep(1)
            if not self._ryu_available():
                raise RuntimeError("Ryu is unavailable on %s:%s" % (RYU_HOST, RYU_PORT))
            with self._lock:
                self._message = "Starting persisted %s topology" % topology_id
            self._start_mininet()
            deadline = time.time() + READINESS_TIMEOUT_SECONDS
            while time.time() < deadline:
                with self._lock:
                    report = self._runtime_report
                    ready = bool(
                        report
                        and report["runtime_topology"] == topology_id
                        and report["stable_seconds"] >= 5.0
                    )
                    if ready:
                        self._status = "ready"
                        self._message = "%s topology is running and stable" % topology_id
                        self._error = None
                        return
                    self._message = "Waiting for Ryu to discover the expected topology"
                if not self._pid_alive(self._pid_from_file()):
                    raise RuntimeError("Mininet exited before topology became ready")
                time.sleep(1)
            raise RuntimeError("topology did not reach expected Ryu readiness before timeout")
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._error = str(exc)
                self._message = str(exc)
        finally:
            with self._lock:
                self._changing = False

    def run_diagnostic(self, command, timeout=45):
        if command not in {"pingall", "ping_server", "http_server"}:
            raise ValueError("unsupported topology diagnostic")
        request_body = (json.dumps({"command": command}) + "\n").encode()
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        try:
            client.connect(CONTROL_SOCKET)
            client.sendall(request_body)
            chunks = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            return json.loads(b"".join(chunks).decode())
        finally:
            client.close()
