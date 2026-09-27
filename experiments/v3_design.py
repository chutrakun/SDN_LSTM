"""Deterministic, balanced design for controlled synthetic V3 lab collection."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from sys import path as sys_path
sys_path.insert(0, str(ROOT))
from topology.topology_config import TOPOLOGIES

VERSION = "sdn_dataset_v3_plan_v1"
CLASSES = ("BENIGN", "UDP_FLOOD", "TCP_SYN_LIKE", "HTTP_FLOOD")
HOSTS = ("h1", "h2", "h3", "h4")
TOPOLOGIES_ORDER = ("star", "tree", "full_mesh")
PROFILE_IDS = ("p00", "p01", "p02", "p03")
REPLICATES = (1, 2)
BEHAVIORS = {
    "BENIGN": ("ping_http", "low_udp", "low_tcp", "idle_bursty_mixed"),
    "UDP_FLOOD": ("steady_low", "steady_mid", "steady_high", "bursty"),
    "TCP_SYN_LIKE": ("steady_low", "steady_mid", "steady_high", "bursty"),
    "HTTP_FLOOD": ("paced_low", "paced_mid", "concurrent", "bursty"),
}
NOMINAL_WIRE_BYTES = (66, 114, 162, 234)
RATE_TIERS = (110, 220, 440, 700)
DURATIONS = (22, 28, 34, 40)


def stable_number(value):
    return int(hashlib.sha256(value.encode()).hexdigest()[:12], 16)


def host_ports(topology):
    """Derive Mininet ofports from exact switch-link then host-link order."""
    profile = TOPOLOGIES[topology]
    next_port = {switch: 0 for switch in profile["switches"]}
    for left, right in profile["edges"]:
        next_port[left] += 1
        next_port[right] += 1
    result = {}
    for host, switch in profile["host_attachments"].items():
        next_port[switch] += 1
        result[host] = {"dpid": int(switch[1:]), "port": next_port[switch],
                        "interface": "%s-eth%s" % (switch, next_port[switch])}
    return result


def make_plan():
    experiments = []
    # Interleave classes within each topology/host/profile block. No class is
    # bound to one host, topology, payload size, duration, or collection epoch.
    for topology in TOPOLOGIES_ORDER:
        for replicate in REPLICATES:
            for profile_index, profile_id in enumerate(PROFILE_IDS):
                for host in HOSTS:
                    nuisance = stable_number("%s:%s:%s:%s" %
                                             (topology, host, profile_id, replicate))
                    nominal_wire = NOMINAL_WIRE_BYTES[nuisance % len(NOMINAL_WIRE_BYTES)]
                    duration = DURATIONS[(nuisance // 7) % len(DURATIONS)]
                    factor = (0.82, 0.94, 1.06, 1.18)[(nuisance // 13) % 4]
                    for scenario in CLASSES:
                        experiment_id = "V3_%s_%s_%s_%s_R%02d" % (
                            topology, host, scenario, profile_id, replicate)
                        # Approximate Ethernet/IP/UDP as 42 bytes and TCP SYN
                        # as 54 bytes. Match nominal packet sizes across the
                        # synthetic UDP and SYN generators before measurement.
                        payload = nominal_wire - (54 if scenario == "TCP_SYN_LIKE" else 42)
                        parameters = {
                            "duration_seconds": duration,
                            "nominal_wire_bytes": nominal_wire,
                            "payload_bytes": payload,
                            "seed": stable_number(experiment_id) % (2**32),
                            "rate_factor": factor,
                            "target_ip": "10.0.0.100",
                        }
                        if scenario in ("UDP_FLOOD", "TCP_SYN_LIKE"):
                            parameters["requested_pps"] = max(1, round(RATE_TIERS[profile_index] * factor))
                            parameters["destination_port"] = 9000 if scenario == "UDP_FLOOD" else 80
                            parameters["burst_on_seconds"] = 2 if profile_id == "p03" else 0
                            parameters["burst_off_seconds"] = 2 if profile_id == "p03" else 0
                        elif scenario == "HTTP_FLOOD":
                            parameters["concurrency"] = (2, 4, 8, 12)[profile_index]
                            parameters["batch_pause_seconds"] = round((.65, .35, .16, .08)[profile_index] / factor, 3)
                            parameters["uri_padding_bytes"] = max(0, nominal_wire - 66)
                        else:
                            parameters["udp_pps"] = max(1, round((14, 55, 18, 125)[profile_index] * factor))
                            parameters["request_pause_seconds"] = round((1.1, 1.0, .28, .4)[profile_index] / factor, 3)
                            parameters["idle_seconds_per_cycle"] = 2 if profile_id == "p03" else 0
                        source = host_ports(topology)[host]
                        experiments.append({
                            "experiment_id": experiment_id,
                            "scenario_label": scenario,
                            "traffic_source_host": host,
                            "topology": topology,
                            "profile_id": profile_id,
                            "profile_behavior": BEHAVIORS[scenario][profile_index],
                            "replicate": replicate,
                            "source_facing": source,
                            "expected_topology": {
                                "switches": len(TOPOLOGIES[topology]["switches"]),
                                "directed_links": 2 * len(TOPOLOGIES[topology]["edges"]),
                            },
                            "parameters": parameters,
                            "holdout_keys": {"run": replicate, "host": host,
                                             "topology": topology, "profile": profile_id},
                        })
    ids = [entry["experiment_id"] for entry in experiments]
    assert len(ids) == len(set(ids)) == 384
    return {"version": VERSION, "classes": list(CLASSES),
            "factor_levels": {"hosts": list(HOSTS), "topologies": list(TOPOLOGIES_ORDER),
                              "profiles": list(PROFILE_IDS), "replicates": list(REPLICATES)},
            "future_holdouts": {"run": "R02", "host": "h4", "topology": "tree",
                                "profile": "p03"},
            "smoke_experiment_ids": [
                "V3_star_h1_BENIGN_p00_R01",
                "V3_star_h2_UDP_FLOOD_p00_R01",
                "V3_full_mesh_h1_UDP_FLOOD_p01_R01",
                "V3_full_mesh_h2_BENIGN_p02_R01",
            ],
            "label_policy": "only manifest-derived source-facing stream receives scenario label; all other switch ports are context",
            "experiments": experiments}


def write_plan(path):
    plan = make_plan()
    path = Path(path)
    content = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError("refusing to replace a different V3 experiment plan")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return plan
