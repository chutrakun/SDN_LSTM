"""Read-only topology checks for opt-in dataset recording."""

import json
from pathlib import Path

from topology.topology_config import (
    DEFAULT_CONFIG_PATH,
    SCHEMA_VERSION,
    TOPOLOGIES,
    expected_directed_edges,
    public_profile,
)


PID_PATH = Path("/tmp/anti_sdn_topology.pid")
TOPOLOGY_SCRIPT = Path(__file__).resolve().parents[1] / "topology/network_topology.py"


def selected_topology(config_path=DEFAULT_CONFIG_PATH):
    """Return a valid selected profile without the manager's write-on-error fallback."""
    try:
        with open(config_path, encoding="utf-8") as handle:
            document = json.load(handle)
        topology_id = document["topology"]
        if document.get("version") != SCHEMA_VERSION or topology_id not in TOPOLOGIES:
            return None
        profile = public_profile(topology_id)
        if any(type(document.get(key)) is not int or document[key] != profile[key]
               for key in ("switches", "physical_links", "directed_links")):
            return None
        if not isinstance(document.get("updated_at"), str) or not document["updated_at"]:
            return None
        return topology_id, document["updated_at"]
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def project_mininet_pid(pid_path=PID_PATH, topology_script=TOPOLOGY_SCRIPT):
    """Accept only the PID file's live process executing this project's topology."""
    try:
        pid = int(Path(pid_path).read_text(encoding="utf-8").strip())
        if pid <= 0:
            return None
        command = Path("/proc/%s/cmdline" % pid).read_bytes().split(b"\0")
        if str(topology_script).encode() not in command:
            return None
        return pid
    except (OSError, ValueError):
        return None


def recorder_topology_ready(datapaths, directed_edges, stable_seconds,
                            config_path=DEFAULT_CONFIG_PATH, pid_path=PID_PATH,
                            mininet_pid=None, required_stable_seconds=5.0):
    """Return (ready, identity) for the selected, exact Ryu topology graph."""
    selected = selected_topology(config_path)
    pid = mininet_pid if mininet_pid is not None else project_mininet_pid(pid_path)
    if selected is None or pid is None:
        return False, None
    topology_id, updated_at = selected
    profile = public_profile(topology_id)
    expected_switches = {int(name[1:]) for name in TOPOLOGIES[topology_id]["switches"]}
    expected_edges = expected_directed_edges(topology_id)
    observed_switches = set(datapaths)
    observed_edges = set(directed_edges)
    ready = (
        observed_switches == expected_switches
        and observed_edges == expected_edges
        and len(observed_switches) == profile["switches"]
        and len(observed_edges) == profile["directed_links"]
        and stable_seconds >= required_stable_seconds
    )
    return ready, (topology_id, updated_at, pid)
