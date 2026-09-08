"""Persistent, validated topology profiles shared by the API and Mininet."""

import datetime
import json
import os
import tempfile


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "current_topology.json")
SCHEMA_VERSION = "sdn_topology_config_v1"
SAFE_DEFAULT = "full_mesh"

TOPOLOGIES = {
    "star": {
        "label": "Star",
        "switches": ("s1",),
        "edges": (),
        "host_attachments": {
            "h1": "s1", "h2": "s1", "h3": "s1", "h4": "s1",
            "h_server": "s1",
        },
    },
    "tree": {
        "label": "Tree",
        "switches": ("s1", "s2", "s3"),
        "edges": (("s2", "s1"), ("s3", "s1")),
        "host_attachments": {
            "h1": "s2", "h2": "s2", "h3": "s3", "h4": "s3",
            "h_server": "s1",
        },
    },
    "full_mesh": {
        "label": "Full Mesh",
        "switches": ("s1", "s2", "s3", "s4"),
        "edges": (
            ("s1", "s2"), ("s1", "s3"), ("s1", "s4"),
            ("s2", "s3"), ("s2", "s4"), ("s3", "s4"),
        ),
        "host_attachments": {
            "h1": "s1", "h2": "s2", "h3": "s3", "h4": "s4",
            "h_server": "s1",
        },
    },
}

ALIASES = {"default": "star", "mesh": "full_mesh"}


def normalize_topology_id(value):
    if not isinstance(value, str):
        raise ValueError("topology must be a string")
    topology_id = ALIASES.get(value.strip().lower(), value.strip().lower())
    if topology_id not in TOPOLOGIES:
        supported = ", ".join(TOPOLOGIES)
        raise ValueError("unsupported topology %r; choose one of: %s" % (value, supported))
    return topology_id


def profile_for(topology_id):
    return TOPOLOGIES[normalize_topology_id(topology_id)]


def expected_directed_edges(topology_id):
    profile = profile_for(topology_id)
    switch_ids = {name: int(name[1:]) for name in profile["switches"]}
    directed = set()
    for left, right in profile["edges"]:
        directed.add((switch_ids[left], switch_ids[right]))
        directed.add((switch_ids[right], switch_ids[left]))
    return directed


def public_profile(topology_id):
    topology_id = normalize_topology_id(topology_id)
    profile = TOPOLOGIES[topology_id]
    return {
        "id": topology_id,
        "label": profile["label"],
        "switches": len(profile["switches"]),
        "physical_links": len(profile["edges"]),
        "directed_links": len(profile["edges"]) * 2,
        "edges": [list(edge) for edge in profile["edges"]],
    }


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def config_document(topology_id, updated_at=None):
    topology_id = normalize_topology_id(topology_id)
    profile = public_profile(topology_id)
    return {
        "version": SCHEMA_VERSION,
        "topology": topology_id,
        "updated_at": updated_at or _utc_now(),
        "switches": profile["switches"],
        "physical_links": profile["physical_links"],
        "directed_links": profile["directed_links"],
    }


def write_topology_config(topology_id, path=DEFAULT_CONFIG_PATH):
    document = config_document(topology_id)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".current_topology.", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(document, handle, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return document


def load_topology_config(path=DEFAULT_CONFIG_PATH):
    try:
        with open(path) as handle:
            document = json.load(handle)
        if document.get("version") != SCHEMA_VERSION:
            raise ValueError("unsupported topology config version")
        topology_id = normalize_topology_id(document.get("topology"))
        return config_document(topology_id, document.get("updated_at")), None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        document = write_topology_config(SAFE_DEFAULT, path)
        return document, "invalid or missing config replaced with safe default: %s" % exc


def supported_profiles():
    return [public_profile(topology_id) for topology_id in TOPOLOGIES]
