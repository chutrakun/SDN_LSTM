import time, numpy as np
from dataclasses import dataclass

@dataclass
class FlowFeature:
    src_ip: str
    dst_ip: str
    protocol: int
    pkt_count: int
    byte_count: int
    duration: float
    pkt_per_second: float
    byte_per_second: float
    avg_pkt_size: float
    flow_iat_mean: float
    flow_iat_std: float
    label: int = 0

def features_to_vector(f: FlowFeature):
    return np.array([[
        f.pkt_count, f.byte_count, f.duration,
        f.pkt_per_second, f.byte_per_second, f.avg_pkt_size,
        f.flow_iat_mean, f.flow_iat_std, f.protocol,
    ]])
