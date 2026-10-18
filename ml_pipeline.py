"""
Score 10-second traffic windows with Isolation Forest.

Flow:
  Elasticsearch `logs`
    → completed 10s windows
    → Isolation Forest scores (contamination=auto)
    → threshold from normal baseline (mean - 3σ)
    → upsert `ml-results` by event_id (no duplicates)

decision_function: higher = more normal, lower = more anomalous.
"""

import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import NotFoundError
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from packet_schema import (
    ES_URL,
    LOGS_INDEX,
    MIN_BASELINE_WINDOWS,
    ML_FEATURE_COLUMNS,
    PORT_SCAN_MULT,
    RESULTS_INDEX,
    THRESHOLD_SIGMA,
    WINDOW_SECONDS,
)

BATCH_SLEEP_SEC = 10
# First poll only: current + previous window. After that, a cursor follows live traffic.
LIVE_LOOKBACK = "now-30s"
FETCH_SIZE = 5000
FETCH_MAX = 50_000

es = Elasticsearch(ES_URL)

scaler = StandardScaler()
model: IsolationForest | None = None
threshold: float | None = None
port_scan_cut: float | None = None
baseline_windows: list[dict] = []
scored_ids: set[str] = set()
fetch_gte: str | None = None


def parse_ts(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def window_start_epoch(ts: datetime) -> int:
    epoch = int(ts.timestamp())
    return epoch - (epoch % WINDOW_SECONDS)


def iso_from_epoch(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000000Z"
    )


def _search_pages(query: dict) -> list[dict]:
    sort = [
        {"@timestamp": {"order": "asc"}},
        {"event_id.keyword": {"order": "asc"}},
    ]
    search_after = None
    hits: list[dict] = []
    while len(hits) < FETCH_MAX:
        kwargs = {
            "index": LOGS_INDEX,
            "query": query,
            "size": min(FETCH_SIZE, FETCH_MAX - len(hits)),
            "sort": sort,
        }
        if search_after is not None:
            kwargs["search_after"] = search_after
        response = es.search(**kwargs)
        batch = response["hits"]["hits"]
        if not batch:
            break
        hits.extend(batch)
        if len(batch) < FETCH_SIZE:
            break
        search_after = batch[-1]["sort"]
    return hits


def current_window_start_epoch() -> int:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    return now_epoch - (now_epoch % WINDOW_SECONDS)


def mark_live_cursor() -> None:
    """Next fetch starts at the open 10s bucket — not the last hour of packets."""
    global fetch_gte
    fetch_gte = iso_from_epoch(current_window_start_epoch())


def fetch_recent_logs():
    gte = fetch_gte or LIVE_LOOKBACK
    hits = _search_pages({"range": {"@timestamp": {"gte": gte}}})

    rows = []
    for hit in hits:
        src = hit["_source"]
        ts = parse_ts(src.get("@timestamp"))
        if ts is None:
            continue
        flags = str(src.get("flags") or "")
        rows.append(
            {
                "bytes": float(src.get("bytes") or 0),
                "src_port": int(src.get("src_port") or 0),
                "dst_port": int(src.get("dst_port") or 0),
                "src_ip": src.get("src_ip", ""),
                "dst_ip": src.get("dst_ip", ""),
                "protocol": src.get("protocol", "OTHER"),
                "flags": flags,
                "is_syn": int("S" in flags.upper()),
                "ts": ts,
            }
        )
    return pd.DataFrame(rows)


def build_windows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []

    current_window = current_window_start_epoch()
    grouped: dict[int, pd.DataFrame] = {}
    for start, group in df.groupby(df["ts"].map(window_start_epoch)):
        grouped[int(start)] = group

    windows = []
    for start, group in sorted(grouped.items()):
        if start >= current_window:
            continue
        event_id = f"window-{start}"
        if event_id in scored_ids:
            continue
        syn_count = int(group["is_syn"].sum()) if "is_syn" in group else 0
        tcp = group[group["protocol"] == "TCP"]
        udp = group[group["protocol"] == "UDP"]
        top_ports = (
            group["dst_port"].value_counts().head(8).index.astype(int).tolist()
        )
        windows.append(
            {
                "event_id": event_id,
                "window_start": iso_from_epoch(start),
                "window_end": iso_from_epoch(start + WINDOW_SECONDS),
                "@timestamp": iso_from_epoch(start + WINDOW_SECONDS),
                "packets": int(len(group)),
                "bytes": float(group["bytes"].sum()),
                "unique_dst_ips": int(group["dst_ip"].nunique()),
                "unique_dst_ports": int(group["dst_port"].nunique()),
                "tcp_count": int(len(tcp)),
                "udp_count": int(len(udp)),
                "syn_count": syn_count,
                "sample_src_ip": str(group["src_ip"].mode().iloc[0])
                if not group["src_ip"].mode().empty
                else "",
                "sample_dst_ip": str(group["dst_ip"].mode().iloc[0])
                if not group["dst_ip"].mode().empty
                else "",
                "top_dst_ports": ",".join(str(p) for p in top_ports),
            }
        )
    return windows


def fit_baseline(windows: list[dict]) -> None:
    global model, threshold, scaler, port_scan_cut
    frame = pd.DataFrame(windows)
    features = frame[ML_FEATURE_COLUMNS].to_numpy(dtype=float)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)
    model = IsolationForest(
        contamination="auto",
        random_state=42,
        n_estimators=200,
    )
    model.fit(scaled)
    scores = model.decision_function(scaled)
    spread = float(max(np.std(scores), 1e-6))
    threshold = float(np.mean(scores) - THRESHOLD_SIGMA * spread)
    max_ports = float(frame["unique_dst_ports"].max())
    port_scan_cut = max(max_ports * PORT_SCAN_MULT, max_ports + 40)
    print(
        f"Baseline ready from {len(windows)} windows. "
        f"score mean={np.mean(scores):.4f} std={spread:.4f} "
        f"threshold={threshold:.4f} (mean - {THRESHOLD_SIGMA}σ) "
        f"scan if unique_dst_ports>={port_scan_cut:.0f}"
    )


def score_window(window: dict) -> dict:
    assert model is not None and threshold is not None
    vector = np.array([[float(window[col]) for col in ML_FEATURE_COLUMNS]])
    scaled = scaler.transform(vector)
    score = float(model.decision_function(scaled)[0])
    scan_hit = (
        port_scan_cut is not None
        and window["unique_dst_ports"] >= port_scan_cut
    )
    is_anomaly = score < threshold or scan_hit
    window = dict(window)
    window["anomaly_score"] = score
    window["threshold"] = threshold
    window["anomaly"] = -1 if is_anomaly else 1
    window["status"] = "ANOMALY" if is_anomaly else "NORMAL"
    return window


def store_result(window: dict) -> None:
    event_id = window["event_id"]
    es.index(index=RESULTS_INDEX, id=event_id, document=window)
    es.index(
        index=RESULTS_INDEX,
        id="current-status",
        document={
            "event_id": "current-status",
            "status": window["status"],
            "anomaly": window["anomaly"],
            "anomaly_score": window["anomaly_score"],
            "threshold": window["threshold"],
            "packets": window["packets"],
            "unique_dst_ports": window["unique_dst_ports"],
            "unique_dst_ips": window["unique_dst_ips"],
            "syn_count": window["syn_count"],
            "@timestamp": window["@timestamp"],
        },
    )
    scored_ids.add(event_id)


def load_scored_ids() -> None:
    try:
        response = es.search(
            index=RESULTS_INDEX,
            query={"prefix": {"event_id.keyword": "window-"}},
            size=1000,
            _source=["event_id"],
        )
    except Exception:
        return
    for hit in response["hits"]["hits"]:
        event_id = hit["_source"].get("event_id")
        if event_id:
            scored_ids.add(event_id)


def main():
    global model, threshold
    print("ML pipeline: live 10s windows only (not the last hour of packets).")
    print("Browse normally first so it can learn a baseline. Ctrl+C to stop.")
    load_scored_ids()
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

        windows = build_windows(df)
        if not windows:
            if model is None:
                print(
                    f"Learning baseline: {len(baseline_windows)}/{MIN_BASELINE_WINDOWS} "
                    "completed windows. Keep browsing."
                )
            else:
                print(
                    "Waiting for the next live 10s window to close "
                    f"(already scored {len(scored_ids)})."
                )
            mark_live_cursor()
            time.sleep(BATCH_SLEEP_SEC)
            continue

        if model is None:
            baseline_windows.extend(windows)
            for window in windows:
                scored_ids.add(window["event_id"])
            print(
                f"Learning baseline: {len(baseline_windows)}/{MIN_BASELINE_WINDOWS} "
                "windows."
            )
            if len(baseline_windows) >= MIN_BASELINE_WINDOWS:
                fit_baseline(baseline_windows)
                for window in baseline_windows:
                    scored = score_window(window)
                    store_result(scored)
                    print(
                        f"{scored['status']:8} ports={scored['unique_dst_ports']:<4} "
                        f"pkts={scored['packets']:<5} score={scored['anomaly_score']:.4f}"
                    )
            mark_live_cursor()
            time.sleep(BATCH_SLEEP_SEC)
            continue

        anomalies = 0
        for window in windows:
            scored = score_window(window)
            store_result(scored)
            if scored["anomaly"] == -1:
                anomalies += 1
            print(
                f"{scored['status']:8} ports={scored['unique_dst_ports']:<4} "
                f"pkts={scored['packets']:<5} score={scored['anomaly_score']:.4f} "
                f"id={scored['event_id']}"
            )
        print(f"Scored {len(windows)} new windows; {anomalies} anomalous.")
        mark_live_cursor()
        time.sleep(BATCH_SLEEP_SEC)


if __name__ == "__main__":
    main()
