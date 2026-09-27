"""Static recorder readiness tests; no Ryu, Mininet, or traffic required."""

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys

from collector.dataset_topology_readiness import (
    project_mininet_pid,
    recorder_topology_ready,
    selected_topology,
)
from collector.sdn_window_recorder import SdnWindowCsvRecorder, EXPERIMENT_STATE_VERSION
from topology.topology_config import (
    TOPOLOGIES,
    config_document,
    expected_directed_edges,
)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))
from v3_collect import recorder_topology_preflight
import traffic_experiment_driver as legacy


class RecorderTopologyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / "topology.json"
        self.missing_pid = Path(self.temporary.name) / "missing.pid"

    def select(self, topology):
        self.config.write_text(json.dumps(config_document(topology)), encoding="utf-8")

    def check(self, switches, edges, seconds=5.1, **overrides):
        return recorder_topology_ready(
            switches, iter(edges), seconds, config_path=self.config,
            pid_path=self.missing_pid, mininet_pid=123, **overrides,
        )[0]

    def test_all_authoritative_profiles_and_v3_preflight(self):
        for topology in TOPOLOGIES:
            with self.subTest(topology=topology):
                self.select(topology)
                switches = {int(name[1:]) for name in TOPOLOGIES[topology]["switches"]}
                edges = expected_directed_edges(topology)
                self.assertTrue(self.check(switches, edges))
                recorder_topology_preflight({
                    "topology": topology,
                    "expected_topology": {
                        "switches": len(switches), "directed_links": len(edges),
                    },
                })
                with self.assertRaises(RuntimeError):
                    recorder_topology_preflight({
                        "topology": topology,
                        "expected_topology": {
                            "switches": len(switches), "directed_links": len(edges) + 2,
                        },
                    })

    def test_mismatches_and_unstable_topology_fail_closed(self):
        self.select("tree")
        switches = {1, 2, 3}
        edges = expected_directed_edges("tree")
        self.assertFalse(self.check({1, 2}, edges))
        self.assertFalse(self.check({1, 2, 4}, edges))
        self.assertFalse(self.check(switches, set()))
        self.assertFalse(self.check(switches, edges | {(2, 3)}))
        self.assertFalse(self.check(switches, edges, seconds=4.99))
        self.assertTrue(self.check(switches, edges, seconds=5.0))
        self.select("star")
        self.assertFalse(self.check(switches, edges))

    def test_invalid_config_and_missing_mininet_fail_closed(self):
        self.select("full_mesh")
        switches = {1, 2, 3, 4}
        edges = expected_directed_edges("full_mesh")
        self.assertIsNone(project_mininet_pid(self.missing_pid))
        self.missing_pid.write_text(str(os.getpid()), encoding="utf-8")
        self.assertIsNone(project_mininet_pid(self.missing_pid))
        self.missing_pid.unlink()
        self.assertFalse(recorder_topology_ready(
            switches, edges, 6, self.config, self.missing_pid)[0])
        for invalid in (
            "{",
            json.dumps({**config_document("full_mesh"), "version": "wrong"}),
            json.dumps({**config_document("full_mesh"), "switches": 3}),
            json.dumps({**config_document("star"), "switches": True}),
            json.dumps({**config_document("full_mesh"), "topology": "unknown"}),
        ):
            self.config.write_text(invalid, encoding="utf-8")
            self.assertIsNone(selected_topology(self.config))
            self.assertFalse(self.check(switches, edges))
        self.assertTrue(self.config.exists())  # No manager fallback wrote over it.

    def test_full_window_and_recorder_local_stability(self):
        # Extract only this controller method so Ryu and live services never import.
        module = ast.parse((ROOT / "controller/ryu_controller.py").read_text())
        method = next(node for node in ast.walk(module)
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "_dataset_window_ready")
        namespace = {
            "recorder_topology_ready": lambda *args, **kwargs:
                recorder_topology_ready(*args, config_path=self.config,
                                        mininet_pid=123, **kwargs),
            "FLOOD_TOPOLOGY_SETTLE_SECONDS": 5,
        }

        class Clock:
            epoch = 1000.0
            tick = 10.0

            def monotonic(self):
                return self.tick

            def time(self):
                return self.epoch

        class Log:
            def info(self, *args):
                pass

        class Recorder:
            enabled = True
            status = None

            def update_topology_status(self, **status):
                self.status = status

        class State:
            dataset_recorder = Recorder()
            datapaths = {1: object()}
            topology = {}
            topology_last_change = 0.0
            dataset_topology_ready_since = None
            dataset_topology_identity = None
            dataset_topology_observation = None
            dataset_topology_observed_at = None

        clock = Clock()
        namespace.update(time=clock, LOG=Log())
        exec(compile(ast.Module(body=[method], type_ignores=[]),
                     "<controller recorder method>", "exec"), namespace)
        gate = namespace["_dataset_window_ready"]
        self.select("star")
        state = State()
        self.assertFalse(gate(state, 998.0))
        self.assertFalse(state.dataset_recorder.status["ready"])
        clock.tick, clock.epoch = 15.0, 1005.0
        self.assertFalse(gate(state, 1004.0))
        clock.tick, clock.epoch = 17.0, 1007.0
        self.assertTrue(gate(state, 1006.0))
        self.assertTrue(state.dataset_recorder.status["ready"])
        self.select("tree")
        clock.tick, clock.epoch = 18.0, 1008.0
        self.assertFalse(gate(state, 1007.0))
        self.assertIsNone(state.dataset_topology_ready_since)
        state.datapaths = {1: object(), 2: object(), 3: object()}
        state.topology = {
            switch: {dst: 1 for src, dst in expected_directed_edges("tree")
                     if src == switch}
            for switch in (1, 2, 3)
        }
        clock.tick, clock.epoch = 19.0, 1009.0
        self.assertFalse(gate(state, 1008.0))
        clock.tick, clock.epoch = 25.0, 1015.0
        self.assertFalse(gate(state, 1014.0))
        self.assertTrue(gate(state, 1016.0))

    def test_driver_uses_selected_profile_and_new_event_sequences(self):
        for topology in TOPOLOGIES:
            with self.subTest(topology=topology):
                self.select(topology)
                selected, profile = legacy.selected_runtime_profile(
                    str(self.config), topology)
                self.assertEqual(selected, topology)
                self.assertEqual(profile["switches"],
                                 len(TOPOLOGIES[topology]["switches"]))
        with self.assertRaises(RuntimeError):
            legacy.selected_runtime_profile(str(self.config), "tree")
        evidence = legacy.new_runtime_evidence(
            {"ml_event_count": 4, "attack_event_count": 2},
            {"ml_event_count": 6, "attack_event_count": 3,
             "ml_events": [
                 {"sequence": 4, "ip": "10.0.0.2"},
                 {"sequence": 5, "ip": "10.0.0.2"}],
             "log": [
                 {"sequence": 2, "ip": "10.0.0.2"},
                 {"sequence": 3, "ip": "10.0.0.2"}],
             "blocked": []},
            "10.0.0.2")
        self.assertEqual([e["sequence"] for e in evidence["matching_ml_events"]], [5])
        self.assertEqual([e["sequence"] for e in evidence["matching_attack_events"]], [3])

    def test_active_state_and_schema_still_gate_rows(self):
        state_path = Path(self.temporary.name) / "state.json"
        recorder = SdnWindowCsvRecorder(enabled=False, state_path=str(state_path))
        window = {"window_start": 11.0, "window_end": 12.0}
        self.assertIsNone(recorder._metadata_for_window(window))
        valid = {
            "version": EXPERIMENT_STATE_VERSION, "recording": True,
            "phase": "ACTIVE", "experiment_id": "V3_TEST",
            "scenario_label": "BENIGN", "attack_source_host": "h1",
            "active_start": 10, "active_end": 20,
        }
        state_path.write_text(json.dumps(valid))
        recorder._refresh_experiment_state()
        self.assertEqual(recorder._metadata_for_window(window)["experiment_id"], "V3_TEST")
        self.assertIsNone(recorder._metadata_for_window(
            {"window_start": 9.0, "window_end": 12.0}))
        for change in ({"phase": "IDLE"}, {"version": "invalid"},
                       {"scenario_label": ""}, {"recording": False}):
            state_path.write_text(json.dumps({**valid, **change}))
            recorder._refresh_experiment_state()
            self.assertIsNone(recorder._metadata_for_window(window))


if __name__ == "__main__":
    unittest.main()
