# Changelog — what changed from the older version

**Branch:** `hasti` (from `main` @ `9122190 before_work`)
**Commit:** `e41824f`

---

## Summary

The older version used a **fake HTTP data simulator** (`bytes`, `response_time`, `status_code`). The new version **captures real packets from this laptop** and feeds router-style fields into the same Elasticsearch + Isolation Forest + Kibana pipeline.

**8 files changed, 509 additions, 36 deletions.**

---

## New files

### `live_capture.py` (+170 lines)
- Sniffs live packets from this Mac's Wi-Fi (`en0`) and loopback (`lo0`) using **Scapy**.
- Extracts **headers only**: `src_ip`, `dst_ip`, `src_port`, `dst_port`, `protocol`, `bytes`, `flags`, `@timestamp`.
- No payloads, passwords, or page bodies are stored.
- Bulk-indexes every 20 packets into Elasticsearch index `logs`.
- Requires `sudo` for raw socket access on macOS.

### `packet_schema.py` (+22 lines)
- Shared constants used by both capture and ML: ES URL, index names, protocol-to-number mapping, and the list of numeric feature columns.
- Ensures capture and ML agree on field names (old version had a mismatch risk between `status_code` and real network fields).

### `demo_burst.py` (+73 lines)
- Generates anomalous-looking traffic **to 127.0.0.1 only** (never the LAN or internet).
- Two modes: TCP port scan (many destination ports) and UDP flood (many tiny packets).
- Purpose: normal browsing looks "normal" to Isolation Forest; this creates outliers for a demo.

### `requirements.txt` (+5 lines)
- Pins dependencies: `requests`, `elasticsearch>=8,<9`, `pandas`, `scikit-learn`, `scapy`.

### `README.md` (+136 lines)
- Full setup and running instructions (Docker, venv, three terminals).
- How to open Kibana Discover (not the home page).
- Safety notes, field descriptions, and known limitations.

### `.gitignore` (+4 lines)
- Ignores `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`.

---

## Modified files

### `ml_pipeline.py` (rewritten, +81 lines / −36 lines)

| Aspect | Old version | New version |
|---|---|---|
| Features | `bytes`, `response_time`, `status_code` | `bytes`, `src_port`, `dst_port`, `protocol_num` |
| Query | `match_all`, all 1000 docs every cycle | `range` on `@timestamp` (last 2 minutes only) |
| Empty handling | Crashes if index is empty | Waits for ≥20 packets, handles `NotFoundError` |
| Structure | Bare `while True` loop, inline imports | `main()`, `fetch_recent_logs()`, `score_and_store()` |
| Output fields | Only `bytes`, `response_time`, `status_code`, `anomaly` | Full packet metadata + `anomaly` |
| Constants | Hardcoded strings | Imported from `packet_schema.py` |

### `data_simulator.py` (+2 lines)
- Added a comment at the top marking it as **fallback only** — prefer `live_capture.py` for real data.

---

## What stayed the same

- `docker-compose.yml` — Elasticsearch 8.12.0 + Kibana 8.12.0, same ports, same network.
- Elasticsearch indexes: `logs` (ingest) and `ml-results` (scored output).
- ML algorithm: Isolation Forest with `contamination=0.05`.
- Kibana as the visualization layer.

---

## Architecture before vs after

**Before:**
```
random numbers → data_simulator.py → Elasticsearch `logs`
    → Isolation Forest (on fake HTTP fields)
    → ml-results → Kibana
```

**After:**
```
This Mac's Wi-Fi + loopback
    → live_capture.py (Scapy, headers only)
    → Elasticsearch `logs`
    → ml_pipeline.py (Isolation Forest on real packet features)
    → ml-results → Kibana Discover
```
