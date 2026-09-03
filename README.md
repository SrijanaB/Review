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

It waits until at least 20 recent packets exist, then scores every ~10 seconds.

- `anomaly = -1` → unusual
- `anomaly = 1` → typical

### 4. Terminal C — optional demo burst (while capture is running)

```bash
source .venv/bin/activate
python demo_burst.py
```

This only hits `127.0.0.1`. Then browse a few websites so real Wi-Fi packets appear too.

### 5. Open Kibana (your logs and analysis)

Must be **http**, not https:

- Home: http://127.0.0.1:5601
- **Logs / analysis:** http://127.0.0.1:5601/app/discover

Kibana’s first screen looks like a product website. That is not the packet table. Use **Discover**.

First time in Discover:

1. Create a data view **Live packets** — index `logs*`, time field `@timestamp`
2. Create a data view **Anomaly results** — index `ml-results*`, time field `@timestamp`
3. Top-left dropdown → **Live packets** for raw traffic
4. Same dropdown → **Anomaly results** for ML flags
5. Top-right time picker → **Last 15 minutes** (empty table is almost always the time range)
6. To see only outliers, search: `anomaly: -1`

If the page says “Kibana is not ready yet”, wait ~1 minute and hard-refresh (Cmd + Shift + R).

## Stop

- Capture / ML: `Ctrl+C` in those terminals
- Elasticsearch + Kibana: `docker compose down`

## Safety

- Headers only: IPs, ports, protocol, length, TCP flags. No passwords, cookies, or page bodies.
- Data stays in local Docker. Nothing is uploaded.
- Demo bursts target **127.0.0.1 only**.

## Fields

| Field | Meaning |
|---|---|
| `src_ip` / `dst_ip` | Who sent / who received |
| `src_port` / `dst_port` | Application ports (443 = HTTPS, 53 = DNS, …) |
| `protocol` | TCP, UDP, ICMP, or OTHER |
| `bytes` | Frame size (length only; payload is not stored) |
| `flags` | TCP flags (S = SYN, A = ACK, …) |
| `anomaly` | `-1` unusual, `1` typical (in `ml-results` only) |

## What you will not see

Packets of other phones, TVs, or IoT on this router. A laptop NIC does not receive their unicast traffic. Whole-home capture is the later Raspberry Pi in-line step.
