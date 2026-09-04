"""Shared contract between live capture and the ML pipeline."""

ES_URL = "http://localhost:9200"
LOGS_INDEX = "logs"
RESULTS_INDEX = "ml-results"

PROTOCOL_TO_NUM = {
    "TCP": 6,
    "UDP": 17,
    "ICMP": 1,
    "OTHER": 0,
}

# Behaviour windows, not single packets.
WINDOW_SECONDS = 10
MIN_BASELINE_WINDOWS = 6
THRESHOLD_SIGMA = 2.0
# Windows with this many times the baseline max unique dest ports are a scan.
PORT_SCAN_MULT = 2.0

# Isolation Forest trains on these aggregated window features.
ML_FEATURE_COLUMNS = [
    "packets",
    "bytes",
    "unique_dst_ips",
    "unique_dst_ports",
    "tcp_count",
    "udp_count",
    "syn_count",
]
