"""Shared contract between live capture and the ML pipeline.

Why this exists: Elasticsearch docs must use the same field names the
Isolation Forest later reads. If capture writes `dst_port` and ML looks
for `status_code`, the model trains on zeros and the dashboard looks empty.
"""

ES_URL = "http://localhost:9200"
LOGS_INDEX = "logs"
RESULTS_INDEX = "ml-results"

PROTOCOL_TO_NUM = {
    "TCP": 6,
    "UDP": 17,
    "ICMP": 1,
    "OTHER": 0,
}

# Numeric columns Isolation Forest can actually train on.
# IPs and flag strings stay in Elasticsearch for Kibana, but they are not
# model features (the forest needs numbers, not addresses).
ML_FEATURE_COLUMNS = ["bytes", "src_port", "dst_port", "protocol_num"]
