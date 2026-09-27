#!/usr/bin/env python3
"""Audit V3 plan, manifests, source-facing windows, and separate context ports."""

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pandas as pd

from v3_design import ROOT, make_plan

DEFAULT_PLAN = ROOT / "data/v3/plan_v1.json"
DEFAULT_DATASET = ROOT / "data/v3/windows_v1.csv"
DEFAULT_MANIFESTS = ROOT / "data/v3/manifests"
DEFAULT_REPORT = ROOT / "data/v3/audit_v1.json"
MEASUREMENTS = ("interval_seconds", "rx_packets_delta", "tx_packets_delta",
                "rx_bytes_delta", "tx_bytes_delta", "rx_pps", "tx_pps",
                "rx_bytes_per_sec", "tx_bytes_per_sec")
STUDY = ("rx_pps", "tx_pps", "rx_bytes_per_sec", "tx_bytes_per_sec",
         "rx_bytes_per_packet", "tx_bytes_per_packet", "interval_seconds")


def describe(series):
    series = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if series.empty:
        return {"count": 0}
    return {"count": int(len(series)), "min": float(series.min()),
            "p05": float(series.quantile(.05)), "median": float(series.median()),
            "p95": float(series.quantile(.95)), "max": float(series.max())}


def group_distribution(view, column):
    result = {}
    for key, group in view.groupby(column, dropna=False):
        result[str(key)] = {"rows": int(len(group)),
                            "measurements": {feature: describe(group[feature]) for feature in STUDY},
                            "zero_rx_pps_percent": float(100 * (group.rx_pps == 0).mean())}
    return result


def audit(plan_path, dataset_path, manifests_path, report_path):
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan != make_plan():
        raise ValueError("V3 plan differs from deterministic design")
    entries = plan["experiments"]
    planned = {name: dict(sorted(Counter(entry[key] for entry in entries).items()))
               for name, key in (("scenario", "scenario_label"), ("host", "traffic_source_host"),
                                 ("topology", "topology"), ("profile", "profile_id"))}
    manifests = {}
    for path in sorted(manifests_path.glob("*.json")) if manifests_path.exists() else []:
        with path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        if manifest.get("experiment_id") in manifests:
            raise ValueError("duplicate experiment manifest")
        manifests[manifest["experiment_id"]] = manifest
    report = {"version": "sdn_dataset_v3_audit_v1", "planned_experiments": len(entries),
              "planned_distribution": planned,
              "manifest_statuses": dict(Counter(value.get("status", "UNKNOWN") for value in manifests.values())),
              "manifest_count": len(manifests),
              "completed_experiments": sorted(key for key, value in manifests.items()
                                              if value.get("status") == "COMPLETE"
                                              and value.get("post_run_health_ok") is True),
              "source_selection": "manifest source_facing dpid/port derived from topology link order and runtime ofport check; never selected by traffic magnitude"}
    if not dataset_path.exists():
        report.update({"status": "NO_DATA", "raw_rows": 0, "source_rows": 0,
                       "context_rows": 0, "blocker": "V3 recorder CSV has not been collected"})
    else:
        raw = pd.read_csv(dataset_path)
        if not set(MEASUREMENTS).issubset(raw.columns):
            raise ValueError("V3 recorder CSV lacks required measurements")
        plan_by_id = {entry["experiment_id"]: entry for entry in entries}
        unknown_ids = sorted(set(raw.experiment_id) - set(plan_by_id))
        if unknown_ids:
            raise ValueError("unplanned experiment IDs in V3 CSV: " + str(unknown_ids))
        for experiment_id in set(raw.experiment_id):
            if experiment_id not in manifests:
                raise ValueError("recorded experiment lacks a manifest: " + experiment_id)
            manifest = manifests[experiment_id]
            entry = plan_by_id[experiment_id]
            if manifest.get("scenario_label") != entry["scenario_label"] or \
               manifest.get("source_facing") != entry["source_facing"]:
                raise ValueError("manifest/plan label or source mismatch: " + experiment_id)
            if set(raw.loc[raw.experiment_id == experiment_id, "scenario_label"]) != {entry["scenario_label"]}:
                raise ValueError("recorder/manifest scenario mismatch: " + experiment_id)
        metadata = raw.experiment_id.map(plan_by_id)
        raw["traffic_source_host"] = metadata.map(lambda value: value["traffic_source_host"])
        raw["topology"] = metadata.map(lambda value: value["topology"])
        raw["profile_id"] = metadata.map(lambda value: value["profile_id"])
        raw["source_dpid"] = metadata.map(lambda value: value["source_facing"]["dpid"])
        raw["source_port"] = metadata.map(lambda value: value["source_facing"]["port"])
        is_source = (raw.dpid == raw.source_dpid) & (raw.port == raw.source_port)
        complete_ids = {key for key, value in manifests.items() if value.get("status") == "COMPLETE"
                        and value.get("post_run_health_ok") is True}
        eligible = raw.experiment_id.isin(complete_ids)
        source = raw[is_source & eligible].copy()
        context = raw[~is_source & eligible].copy()
        incomplete = raw[~eligible].copy()
        # Context retains the run scenario only as audit metadata, never as a
        # training label or a column named like the labeled source view.
        context.rename(columns={"scenario_label": "run_scenario_label"}, inplace=True)
        for frame, label in ((source, "SOURCE_FACING"), (context, "CONTEXT_ONLY")):
            frame["observation_role"] = label
            frame["training_label"] = frame.scenario_label if label == "SOURCE_FACING" else ""
        for frame in (source, context):
            frame["rx_bytes_per_packet"] = frame.rx_bytes_delta.div(
                frame.rx_packets_delta.replace(0, np.nan)).fillna(0)
            frame["tx_bytes_per_packet"] = frame.tx_bytes_delta.div(
                frame.tx_packets_delta.replace(0, np.nan)).fillna(0)
        report.update({
            "status": "AUDITED", "raw_rows": int(len(raw)),
            "source_rows": int(len(source)), "context_rows": int(len(context)),
            "excluded_incomplete_or_unhealthy_rows": int(len(incomplete)),
            "recorded_rows_by_experiment": {str(k): int(v) for k, v in
                                            raw.experiment_id.value_counts().sort_index().items()},
            "source_rows_by_experiment": {str(k): int(v) for k, v in
                                          source.experiment_id.value_counts().sort_index().items()},
            "missing_values": {name: int(count) for name, count in raw.isna().sum().items()},
            "nonfinite_values": {name: int((~np.isfinite(pd.to_numeric(raw[name], errors="coerce"))).sum())
                                 for name in MEASUREMENTS},
            "negative_values": {name: int((raw[name] < 0).sum()) for name in MEASUREMENTS},
            "duplicate_windows": int(raw.duplicated(["experiment_id", "dpid", "port", "window_end"]).sum()),
            "source_distributions": {name: group_distribution(source, column) for name, column in
                                     (("scenario", "scenario_label"), ("host", "traffic_source_host"),
                                      ("topology", "topology"), ("profile", "profile_id"))},
            "context_zero_rx_pps_percent": float(100 * (context.rx_pps == 0).mean()) if len(context) else None,
        })
        source_path = report_path.parent / "source_windows_v1.csv"
        context_path = report_path.parent / "context_windows_v1.csv"
        source.to_csv(source_path, index=False)
        context.to_csv(context_path, index=False)
        if len(incomplete):
            incomplete.to_csv(report_path.parent / "excluded_windows_v1.csv", index=False)
        report["source_view_path"] = str(source_path)
        report["context_view_path"] = str(context_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "planned_experiments", "manifest_count",
                                                    "raw_rows", "source_rows", "context_rows")}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--manifests", type=Path, default=DEFAULT_MANIFESTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    audit(args.plan, args.dataset, args.manifests, args.report)
