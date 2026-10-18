# SHIELD — live laptop capture (Phase 1)

Secure Home Intelligent Edge Log Detection. This phase streams **real packets from this Mac** into Elasticsearch, scores them with Isolation Forest, and shows them in Kibana Discover.

You see **this laptop only** (current Wi-Fi + loopback). Other devices on the same router are not visible without in-line hardware (Raspberry Pi later).

## What was implemented

| File | Role |
|---|---|
| `docker-compose.yml` | Elasticsearch (`:9200`) + Kibana (`:5601`) |
| `packet_schema.py` | Shared field names for capture and ML |
| `live_capture.py` | Sniffs this Mac, writes header-only JSON to index `logs` |
| `ml_pipeline.py` | Isolation Forest on recent packets → index `ml-results` |
| `demo_burst.py` | Optional localhost-only scan/flood so anomalies appear in a demo |
| `create_kibana_dashboard.py` | Creates the **SHIELD live traffic** Analytics dashboard in Kibana |
| `data_simulator.py` | Old fake HTTP generator (fallback only; do not use for the review) |

```
Wi-Fi NIC + lo0
    → live_capture.py (headers only)
    → Elasticsearch index `logs`
    → ml_pipeline.py (Isolation Forest)
    → Elasticsearch index `ml-results`
    → Kibana Discover
```

## Prerequisites

- Docker Desktop running (whale icon in the menu bar)
- Python 3.11+
- macOS admin password (needed once for packet capture)

## Setup (once)

```bash
cd Review
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d
```

Wait until Elasticsearch answers with JSON:

```bash
curl http://127.0.0.1:9200
```

If this fails, start **Docker Desktop** first, wait until it is idle, then run `docker compose up -d` again.

## Running steps (every demo)

Use **three terminals** from the project folder. Keep them all open.

### 1. Start ELK (if containers are not already up)

```bash
docker compose up -d
```

### 2. Terminal A — live capture

Needs sudo (raw sockets). Use the venv interpreter:

```bash
sudo .venv/bin/python live_capture.py
```

You should see lines like `TCP 192.168.x.x:… -> … 443`. macOS may ask for packet-filter permission once.

### 3. Terminal B — ML scoring

```bash
source .venv/bin/activate
python ml_pipeline.py
```

It waits for **8 completed 10-second windows** of normal browsing, fits Isolation Forest with `contamination="auto"`, and sets a threshold at **mean − 3σ** of those baseline scores. It does **not** assume 5% of traffic is malicious.

- `status = NORMAL` / `anomaly = 1` → score above the learned threshold
- `status = ANOMALY` / `anomaly = -1` → score below the threshold

Each window is stored once (`event_id = window-<epoch>`).

### 4. Terminal C — demo burst (only after the baseline is ready)

Browse normally for ~90 seconds first. When the ML terminal prints `Baseline ready`, then:

```bash
source .venv/bin/activate
python demo_burst.py
```

That hits **127.0.0.1 only** (about 300 ports + 500 UDP packets in a few seconds). The next completed window should show a high `unique_dst_ports` count and `ANOMALY`.

### 5. Open Kibana (your logs and analysis)

Must be **http**, not https:

- Home: http://127.0.0.1:5601
- **Analytics dashboard (charts):** http://127.0.0.1:5601/app/dashboards#/view/shield-live-traffic
- **Data visualizer (field stats):** http://127.0.0.1:5601/app/dashboards#/view/shield-data-visualizer
- **ML Data Visualizer (logs):** http://127.0.0.1:5601/app/ml/datavisualizer_index_view?index=75ce9249-fc92-48f3-87a9-29e4f25787d0
- **ML Data Visualizer (ml-results):** http://127.0.0.1:5601/app/ml/datavisualizer_index_view?index=cabb1875-67ae-4343-ad04-bac763cfecb0
- **Discover (row table):** http://127.0.0.1:5601/app/discover

Kibana’s first screen looks like a product website. That is not your data.

**Analytics → Dashboard** should list **SHIELD live traffic**. If it is missing after a fresh `docker compose up`, recreate it:

```bash
source .venv/bin/activate
python create_kibana_dashboard.py
```

**Analytics → Dashboard** also lists **SHIELD data visualizer**: total packets, unique destination IPs, average size, anomaly count, plus field tables for `src_ip`, `dst_port`, `protocol`, and `anomaly`.

Kibana **Machine Learning → Data Visualizer → Data view** shows the official field-by-field stats page. Pick **Live packets** or **Anomaly results**.

The live-traffic dashboard centerpiece is **anomalous windows over time**, plus unique destination ports per window and an investigate table (`status: ANOMALY`). Supporting charts: normal vs anomaly, packet count, protocol. Set time to **Last 15 minutes**. After changing ML fields, recreate:

```bash
python create_kibana_dashboard.py
```

Discover on **Anomaly results** and filter `status: ANOMALY` to see which window caused the spike (`unique_dst_ports`, `packets`, `syn_count`, `anomaly_score`).

**Discover** (the table):

1. Data views: **Live packets** (`logs*`) and **Anomaly results** (`ml-results*`)
2. Top-left dropdown → pick one of those views
3. Top-right time picker → **Last 15 minutes** or **Last 24 hours**
4. To see only outliers: `status: ANOMALY`

If Kibana says **Create a data view**, do not skip it — fill the form:

1. Name: `Live packets`
2. Index pattern: `logs*` (you should see a hit count)
3. Timestamp field: `@timestamp`
4. Save
5. Repeat: name `Anomaly results`, index pattern `ml-results*`, timestamp `@timestamp`

Or recreate both from the project folder:

```bash
source .venv/bin/activate
python create_kibana_dashboard.py
```

If the page says “Kibana is not ready yet”, wait ~1 minute and hard-refresh (Cmd + Shift + R).

## Stop

- Capture / ML: `Ctrl+C` in those terminals
- Elasticsearch + Kibana: `docker compose down`

## Safety

- Headers only: IPs, ports, protocol, length, TCP flags. No passwords, cookies, or page bodies.
- Data stays in local Docker. Nothing is uploaded.
- Demo bursts target **127.0.0.1 only**.

## Fields

Packet fields in `logs`:

| Field | Meaning |
|---|---|
| `event_id` | Unique packet id (used as Elasticsearch `_id`) |
| `src_ip` / `dst_ip` | Who sent / who received |
| `src_port` / `dst_port` | Application ports |
| `protocol` / `bytes` / `flags` | Header metadata only |

Window fields in `ml-results`:

| Field | Meaning |
|---|---|
| `event_id` | `window-<epoch>` — one document per 10s window |
| `packets` / `bytes` | Volume in that window |
| `unique_dst_ports` / `unique_dst_ips` | Behaviour features (scan = many ports) |
| `tcp_count` / `udp_count` / `syn_count` | Protocol mix |
| `anomaly_score` | Isolation Forest `decision_function` (lower = more unusual) |
| `threshold` | Learned from baseline (`mean − 3σ`) |
| `anomaly` / `status` | `-1` / `ANOMALY` or `1` / `NORMAL` |

## What you will not see

Packets of other phones, TVs, or IoT on this router. A laptop NIC does not receive their unicast traffic. Whole-home capture is the later Raspberry Pi in-line step.
