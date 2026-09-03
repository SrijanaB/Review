"""
Score recent live packets with Isolation Forest and write `ml-results`.

Technical flow:
  Elasticsearch `logs` → scale numeric features → Isolation Forest → `ml-results`

Why Isolation Forest:
  Home traffic has no reliable labels. The forest flags points that are easy
  to isolate (unusual size, rare ports, odd protocol mix) as anomalies (-1).
"""

import time

import pandas as pd
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from packet_schema import ES_URL, LOGS_INDEX, ML_FEATURE_COLUMNS, RESULTS_INDEX

MIN_ROWS = 20
BATCH_SLEEP_SEC = 10
LOOKBACK = "now-2m"

es = Elasticsearch(ES_URL)


def fetch_recent_logs():
    """Only the last two minutes — otherwise we re-score the same 1000 docs forever."""
    query = {"range": {"@timestamp": {"gte": LOOKBACK}}}
    try:
        response = es.search(
            index=LOGS_INDEX,
            query=query,
            size=1000,
            sort=[{"@timestamp": {"order": "desc"}}],
        )
    except Exception:
        # First documents may not be mapped as date yet; still return them.
        response = es.search(
            index=LOGS_INDEX,
            query={"match_all": {}},
            size=1000,
        )
    rows = []
    for hit in response["hits"]["hits"]:
        src = hit["_source"]
        rows.append(
            {
                "bytes": float(src.get("bytes") or 0),
                "src_port": int(src.get("src_port") or 0),
                "dst_port": int(src.get("dst_port") or 0),
                "protocol_num": int(src.get("protocol_num") or 0),
                "src_ip": src.get("src_ip", ""),
                "dst_ip": src.get("dst_ip", ""),
                "protocol": src.get("protocol", "OTHER"),
                "flags": src.get("flags", ""),
                "@timestamp": src.get("@timestamp"),
            }
        )
    return pd.DataFrame(rows)


def score_and_store(df):
    scaler = StandardScaler()
    scaled = scaler.fit_transform(df[ML_FEATURE_COLUMNS])

    # 5% expected outliers — typical for mixed browsing + a demo burst.
    model = IsolationForest(contamination=0.05, random_state=42)
    df = df.copy()
    df["anomaly"] = model.fit_predict(scaled)

    for _, row in df.iterrows():
        es.index(
            index=RESULTS_INDEX,
            document={
                "src_ip": row["src_ip"],
                "dst_ip": row["dst_ip"],
                "src_port": int(row["src_port"]),
                "dst_port": int(row["dst_port"]),
                "protocol": row["protocol"],
                "bytes": float(row["bytes"]),
                "flags": row["flags"],
                "anomaly": int(row["anomaly"]),
                "@timestamp": row["@timestamp"],
            },
        )
    return int((df["anomaly"] == -1).sum()), len(df)


def main():
    print("ML pipeline watching Elasticsearch for live packets. Ctrl+C to stop.")
    while True:
        try:
            df = fetch_recent_logs()
        except NotFoundError:
            print(f"Index `{LOGS_INDEX}` not created yet. Start live_capture.py first.")
            time.sleep(BATCH_SLEEP_SEC)
            continue
        except Exception as exc:
            print(f"Could not read Elasticsearch: {exc}")
            time.sleep(BATCH_SLEEP_SEC)
            continue

        if df.empty or len(df) < MIN_ROWS:
            print(f"Need at least {MIN_ROWS} recent packets (have {len(df)}). Waiting.")
            time.sleep(BATCH_SLEEP_SEC)
            continue

        anomalies, total = score_and_store(df)
        print(f"Processed {total} packets; flagged {anomalies} as anomalous.")
        time.sleep(BATCH_SLEEP_SEC)


if __name__ == "__main__":
    main()
