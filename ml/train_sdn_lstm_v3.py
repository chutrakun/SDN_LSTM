"""Train/evaluate the versioned binary SDN port-window model.

The split is by complete Mininet experiment.  Preprocessing is fitted only on
training experiments and the legacy active model is evaluated on the same
unseen holdout before the new artifact is written.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, confusion_matrix, log_loss,
                             precision_recall_fscore_support)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, LabelEncoder, StandardScaler
import tensorflow as tf
from ml.sdn_lstm_v3_features import FEATURES, FEATURE_SPEC, SCHEMA_VERSION, feature_vector


SOURCE = ROOT / "data/v3/source_windows_v1.csv"
ARTIFACTS = ROOT / "ml/model/sdn_lstm_v3"
SEED = 42
SEQUENCE_LENGTH = 5
CLASSES = ("BENIGN", "UDP_FLOOD")

def experiment_ids():
    split = {"train": [], "validation": [], "test": []}
    for topology in ("star", "tree", "full_mesh"):
        for host, profile in (("h1", "p00"), ("h1", "p01"),
                              ("h2", "p02"), ("h2", "p03")):
            for label in CLASSES:
                split["train"].append(
                    f"V3_{topology}_{host}_{label}_{profile}_R01")
        for label in CLASSES:
            split["validation"].append(
                f"V3_{topology}_h3_{label}_p01_R01")
            replicate = 1 if topology == "star" and label == "BENIGN" else 2
            split["test"].append(
                f"V3_{topology}_h4_{label}_p03_R{replicate:02d}")
    return split


def feature_frame(frame):
    values = np.stack([feature_vector(
        row.interval_seconds, row.rx_packets_delta, row.tx_packets_delta,
        row.rx_bytes_delta, row.tx_bytes_delta, row.rx_bytes_per_sec,
        row.tx_bytes_per_sec, row.rx_pps, row.tx_pps,
    ) for row in frame.itertuples(index=False)])
    result = pd.DataFrame(values, columns=FEATURES, index=frame.index)
    return result


def softmax(logits, temperature=1.0):
    scaled = np.asarray(logits, dtype=np.float64) / temperature
    scaled -= scaled.max(axis=1, keepdims=True)
    exp = np.exp(scaled)
    return exp / exp.sum(axis=1, keepdims=True)


def make_sequences(frame, transformed, labels):
    sequences, truth, records = [], [], []
    for _, positions in frame.groupby("experiment_id", sort=True).indices.items():
        positions = list(positions)
        for end in range(SEQUENCE_LENGTH - 1, len(positions)):
            chosen = positions[end - SEQUENCE_LENGTH + 1:end + 1]
            sequences.append(transformed[chosen])
            truth.append(labels[positions[end]])
            records.append(frame.iloc[positions[end]].to_dict())
    return (np.stack(sequences), pd.DataFrame(records),
            np.asarray(truth, dtype=np.int64))


def expected_calibration_error(y, probabilities, bins=10):
    confidence = probabilities.max(axis=1)
    correct = probabilities.argmax(axis=1) == y
    total = len(y)
    value = 0.0
    for low, high in zip(np.linspace(0, 1, bins + 1)[:-1],
                         np.linspace(0, 1, bins + 1)[1:]):
        mask = (confidence > low) & (confidence <= high)
        if mask.any():
            value += mask.sum() / total * abs(correct[mask].mean() - confidence[mask].mean())
    return float(value)


def metrics(y, probabilities):
    prediction = probabilities.argmax(axis=1)
    matrix = confusion_matrix(y, prediction, labels=[0, 1])
    precision, recall, f1, support = precision_recall_fscore_support(
        y, prediction, labels=[0, 1], zero_division=0)
    return {
        "accuracy": float(accuracy_score(y, prediction)),
        "confusion_matrix": matrix.tolist(),
        "class_order": list(CLASSES),
        "precision": dict(zip(CLASSES, precision.astype(float))),
        "recall": dict(zip(CLASSES, recall.astype(float))),
        "f1": dict(zip(CLASSES, f1.astype(float))),
        "support": dict(zip(CLASSES, support.astype(int))),
        "macro_f1": float(f1.mean()),
        "benign_false_positive_rate": float(matrix[0, 1] / matrix[0].sum()),
        "nll": float(log_loss(y, probabilities, labels=[0, 1])),
        "brier": float(np.mean(np.sum((probabilities - np.eye(2)[y]) ** 2, axis=1))),
        "ece_10_bins": expected_calibration_error(y, probabilities),
        "confidence": {
            "min": float(probabilities.max(axis=1).min()),
            "median": float(np.median(probabilities.max(axis=1))),
            "max": float(probabilities.max(axis=1).max()),
        },
    }


def run_metrics(frame, y, probabilities):
    rows = []
    for experiment_id, positions in frame.groupby("experiment_id", sort=True).indices.items():
        positions = np.asarray(list(positions), dtype=int)
        mean_probability = probabilities[positions].mean(axis=0)
        rows.append({
            "experiment_id": experiment_id,
            "true": CLASSES[int(y[positions[0]])],
            "prediction": CLASSES[int(mean_probability.argmax())],
            "confidence": float(mean_probability.max()),
            "windows": int(len(positions)),
        })
    true = np.asarray([CLASSES.index(row["true"]) for row in rows])
    probability = np.asarray([
        [row["confidence"], 1 - row["confidence"]]
        if row["prediction"] == "BENIGN" else
        [1 - row["confidence"], row["confidence"]] for row in rows
    ])
    return {"aggregate": metrics(true, probability), "runs": rows}


def legacy_features(frame):
    duration_us = frame.interval_seconds.to_numpy(np.float64) * 1e6
    packets = frame.rx_packets_delta.to_numpy(np.float64)
    return pd.DataFrame(np.column_stack([
        pd.to_numeric(frame.last_dst_port, errors="coerce").fillna(0),
        pd.to_numeric(frame.last_protocol, errors="coerce").fillna(0),
        duration_us, packets, np.zeros(len(frame)), frame.rx_bytes_delta,
        np.zeros(len(frame)), frame.rx_bytes_per_sec, frame.rx_pps,
        duration_us / np.maximum(packets, 1),
    ]), columns=("Destination Port", "Protocol", "Flow Duration",
                 "Total Fwd Packets", "Total Backward Packets",
                 "Total Length of Fwd Packets", "Total Length of Bwd Packets",
                 "Flow Bytes/s", "Flow Packets/s", "Flow IAT Mean"))


def legacy_evaluation(frame, y):
    model_dir = ROOT / "ml/model/uploads"
    model = tf.keras.models.load_model(model_dir / "20260515_154411_lstm_sdn_model.h5", compile=False)
    scaler = joblib.load(model_dir / "20260515_154411_scaler.pkl")
    encoder = joblib.load(model_dir / "20260515_154411_label_encoder.pkl")
    raw = legacy_features(frame)
    probabilities = model.predict(scaler.transform(raw).reshape(len(raw), 1, 10), verbose=0)
    labels = encoder.inverse_transform(probabilities.argmax(axis=1))
    binary = np.column_stack([
        np.where(labels == "BENIGN", probabilities.max(axis=1), 1 - probabilities.max(axis=1)),
        np.where(labels != "BENIGN", probabilities.max(axis=1), 1 - probabilities.max(axis=1)),
    ])
    return {"window": metrics(y, binary), "run": run_metrics(frame, y, binary),
            "predicted_labels": pd.Series(labels).value_counts().to_dict()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.artifacts.exists() and any(args.artifacts.iterdir()) and not args.force:
        parser.error("artifact directory is not empty; use --force deliberately")
    ids = experiment_ids()
    all_ids = set(sum(ids.values(), []))
    raw = pd.read_csv(args.source)
    view = raw[raw.experiment_id.isin(all_ids)].copy()
    if set(view.experiment_id) != all_ids:
        raise ValueError("missing selected experiments: " + str(sorted(all_ids - set(view.experiment_id))))
    if view.duplicated(["experiment_id", "dpid", "port", "window_end"]).any():
        raise ValueError("duplicate monitoring windows")
    parts = {name: view[view.experiment_id.isin(group)].copy().sort_values(
        ["experiment_id", "window_start"]).reset_index(drop=True)
             for name, group in ids.items()}
    assert not (set(ids["train"]) & set(ids["validation"]) or
                set(ids["train"]) & set(ids["test"]) or
                set(ids["validation"]) & set(ids["test"]))
    encoder = LabelEncoder().fit(CLASSES)
    matrices = {name: feature_frame(part) for name, part in parts.items()}
    labels = {name: encoder.transform(part.scenario_label) for name, part in parts.items()}
    preprocessor = Pipeline([
        ("log1p", FunctionTransformer(np.log1p, validate=False)),
        ("standard", StandardScaler()),
    ])
    preprocessor.fit(matrices["train"])
    preprocessor.sdn_schema_version = SCHEMA_VERSION
    preprocessor.sdn_feature_names = FEATURES
    transformed = {name: preprocessor.transform(matrix)
                   for name, matrix in matrices.items()}
    sequenced = {name: make_sequences(parts[name], transformed[name], labels[name])
                 for name in parts}
    tf.keras.utils.set_random_seed(SEED)
    try:
        tf.config.experimental.enable_op_determinism()
    except RuntimeError:
        pass
    inputs = tf.keras.layers.Input(shape=(SEQUENCE_LENGTH, len(FEATURES)))
    hidden = tf.keras.layers.LSTM(24)(inputs)
    hidden = tf.keras.layers.Dropout(.15)(hidden)
    hidden = tf.keras.layers.Dense(12, activation="relu")(hidden)
    logits = tf.keras.layers.Dense(2, name="logits")(hidden)
    base = tf.keras.Model(inputs, logits)
    base.compile(optimizer=tf.keras.optimizers.Adam(.001),
                 loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True))
    history = base.fit(sequenced["train"][0], sequenced["train"][2],
                       validation_data=(sequenced["validation"][0], sequenced["validation"][2]),
                       epochs=120, batch_size=16, shuffle=True, verbose=0,
                       callbacks=[tf.keras.callbacks.EarlyStopping(
                           monitor="val_loss", patience=18, restore_best_weights=True)])
    validation_logits = base.predict(sequenced["validation"][0], verbose=0)
    # A small validation set must not sharpen logits into false certainty.
    candidates = np.linspace(1.0, 4.0, 241)
    temperature = min(candidates, key=lambda value: log_loss(
        sequenced["validation"][2], softmax(validation_logits, value), labels=[0, 1]))
    scaled_logits = tf.keras.layers.Rescaling(1.0 / float(temperature),
                                              name="temperature_scale")(base.output)
    calibrated = tf.keras.Model(base.input, tf.keras.layers.Softmax(name="probabilities")(scaled_logits))
    probabilities = {name: calibrated.predict(data[0], verbose=0)
                     for name, data in sequenced.items()}
    report = {
        "version": "sdn_lstm_v3_binary_v1",
        "classes": list(CLASSES), "ordered_features": list(FEATURES),
        "feature_spec": FEATURE_SPEC, "split_experiment_ids": ids,
        "split_rows": {name: int(len(part)) for name, part in parts.items()},
        "split_runs": {name: int(part.experiment_id.nunique()) for name, part in parts.items()},
        "class_rows": {name: {str(k): int(v) for k, v in part.scenario_label.value_counts().items()}
                       for name, part in parts.items()},
        "duplicate_windows": int(view.duplicated(["experiment_id", "dpid", "port", "window_end"]).sum()),
        "exact_feature_duplicates": int(feature_frame(view).duplicated().sum()),
        "split_overlap": {"train_validation": [], "train_test": [], "validation_test": []},
        "preprocessing": "reject invalid values; log1p then StandardScaler fitted on train windows only",
        "temperature": float(temperature), "epochs_ran": len(history.history["loss"]),
        "legacy_active_model_id_5": legacy_evaluation(sequenced["test"][1], sequenced["test"][2]),
        "new_model": {name: {"window": metrics(sequenced[name][2], probabilities[name]),
                              "run": run_metrics(sequenced[name][1], sequenced[name][2], probabilities[name])}
                      for name in parts},
        "feature_ranges": {name: {column: {"min": float(matrix[column].min()),
                                             "median": float(matrix[column].median()),
                                             "max": float(matrix[column].max())}
                                  for column in FEATURES}
                           for name, matrix in matrices.items()},
        "reproducibility": {"seed": SEED, "tensorflow": tf.__version__,
                            "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest()},
    }
    args.artifacts.mkdir(parents=True, exist_ok=True)
    calibrated.save(args.artifacts / "model.h5")
    joblib.dump(preprocessor, args.artifacts / "preprocessor.joblib")
    joblib.dump(encoder, args.artifacts / "label_encoder.pkl")
    json_default = lambda value: value.item() if isinstance(value, np.generic) else str(value)
    (args.artifacts / "evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=json_default) + "\n")
    metadata = {"version": report["version"], "classes": list(CLASSES),
                "ordered_features": list(FEATURES), "feature_spec": FEATURE_SPEC,
                "input_shape": [SEQUENCE_LENGTH, len(FEATURES)],
                "sequence_length": SEQUENCE_LENGTH, "temperature": float(temperature),
                "production_ml_threshold": .90, "split_experiment_ids": ids,
                "seed": SEED, "source_sha256": report["reproducibility"]["source_sha256"]}
    (args.artifacts / "training_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    checksums = {name: hashlib.sha256((args.artifacts / name).read_bytes()).hexdigest()
                 for name in ("model.h5", "preprocessor.joblib", "label_encoder.pkl",
                              "training_metadata.json", "evaluation.json")}
    (args.artifacts / "artifact_manifest.json").write_text(json.dumps(
        {"version": report["version"], "sha256": checksums}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"legacy_test": report["legacy_active_model_id_5"]["window"],
                      "new_test": report["new_model"]["test"]["window"],
                      "temperature": float(temperature), "artifacts": str(args.artifacts)},
                     indent=2, default=json_default))


if __name__ == "__main__":
    main()
