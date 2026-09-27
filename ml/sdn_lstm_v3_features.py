"""Canonical feature schema shared by V3 training and live inference."""

import numpy as np


SCHEMA_VERSION = "sdn_port_window_v3"
FEATURES = (
    "Window Duration us", "RX Packets", "TX Packets", "RX Bytes", "TX Bytes",
    "Total Bytes/s", "Total Packets/s", "Mean Packet IAT us",
)
FEATURE_SPEC = {
    "Window Duration us": "interval_seconds * 1e6",
    "RX Packets": "OVS rx_packets delta on the source-facing switch port",
    "TX Packets": "OVS tx_packets delta on the source-facing switch port",
    "RX Bytes": "OVS rx_bytes delta on the source-facing switch port",
    "TX Bytes": "OVS tx_bytes delta on the source-facing switch port",
    "Total Bytes/s": "rx_bytes_per_sec + tx_bytes_per_sec",
    "Total Packets/s": "rx_pps + tx_pps",
    "Mean Packet IAT us": "window duration us / max(RX Packets + TX Packets, 1)",
}


def feature_vector(interval_seconds, rx_packets_delta, tx_packets_delta,
                   rx_bytes_delta, tx_bytes_delta, rx_bytes_per_sec,
                   tx_bytes_per_sec, rx_pps, tx_pps):
    duration_us = float(interval_seconds) * 1_000_000.0
    total_packets = float(rx_packets_delta) + float(tx_packets_delta)
    values = np.asarray([
        duration_us, rx_packets_delta, tx_packets_delta,
        rx_bytes_delta, tx_bytes_delta,
        float(rx_bytes_per_sec) + float(tx_bytes_per_sec),
        float(rx_pps) + float(tx_pps),
        duration_us / max(total_packets, 1.0),
    ], dtype=np.float64)
    if values.shape != (len(FEATURES),) or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("invalid sdn_port_window_v3 feature vector")
    return values
