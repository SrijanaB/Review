"""
Sniff this laptop's live packets and stream header-only logs to Elasticsearch.

Technical flow:
  NIC (current Wi-Fi + loopback) → Scapy → header JSON → Elasticsearch `logs`

Why:
  The old simulator invented HTTP fields. SHIELD is a network IDS, so the
  model needs real packet metadata (who talked to whom, ports, size, flags).

Limits:
  You see THIS Mac only. Other phones on the same router are not visible.
  Loopback (lo0) is included so localhost demo bursts show up in Kibana.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests
from scapy.all import ICMP, IP, TCP, UDP, conf, sniff

from packet_schema import ES_URL, LOGS_INDEX, PROTOCOL_TO_NUM

BULK_SIZE = 20
SNIFF_TIMEOUT_SEC = 2.0
ES_BULK_URL = f"{ES_URL}/_bulk"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def detect_interfaces():
    """Wi-Fi/Ethernet for real traffic, plus lo0 so localhost demos are visible."""
    ifaces = []
    try:
        output = subprocess.check_output(
            ["route", "-n", "get", "default"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in output.splitlines():
            if "interface:" in line:
                name = line.split(":", 1)[1].strip()
                if name:
                    ifaces.append(name)
                break
    except (OSError, subprocess.CalledProcessError):
        fallback = str(conf.iface) if conf.iface else "en0"
        ifaces.append(fallback)

    if "lo0" not in ifaces:
        ifaces.append("lo0")
    return ifaces


def packet_to_doc(pkt):
    """Keep IP/TCP/UDP/ICMP headers only. Never store payload bytes."""
    if IP not in pkt:
        return None

    ip = pkt[IP]
    src_port = 0
    dst_port = 0
    flags = ""
    protocol = "OTHER"

    if TCP in pkt:
        protocol = "TCP"
        src_port = int(pkt[TCP].sport)
        dst_port = int(pkt[TCP].dport)
        flags = str(pkt[TCP].flags)
    elif UDP in pkt:
        protocol = "UDP"
        src_port = int(pkt[UDP].sport)
        dst_port = int(pkt[UDP].dport)
    elif ICMP in pkt:
        protocol = "ICMP"

    return {
        "src_ip": ip.src,
        "dst_ip": ip.dst,
        "src_port": src_port,
        "dst_port": dst_port,
        "protocol": protocol,
        "protocol_num": PROTOCOL_TO_NUM[protocol],
        "bytes": int(len(pkt)),
        "flags": flags,
        "@timestamp": utc_now(),
    }


def flush_docs(docs):
    """Bulk-index so a busy Wi-Fi NIC does not open one HTTP request per packet."""
    if not docs:
        return 0

    lines = []
    for doc in docs:
        lines.append(f'{{"index":{{"_index":"{LOGS_INDEX}"}}}}')
        lines.append(json.dumps(doc))
    payload = "\n".join(lines) + "\n"

    try:
        response = requests.post(
            ES_BULK_URL,
            data=payload,
            headers={"Content-Type": "application/x-ndjson"},
            timeout=5,
        )
        response.raise_for_status()
        return len(docs)
    except requests.RequestException as exc:
        print(f"Elasticsearch not reachable ({exc}). Will retry on next batch.")
        return 0


def main():
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Packet capture needs raw sockets.")
        print("Run:  sudo .venv/bin/python live_capture.py")
        sys.exit(1)

    ifaces = detect_interfaces()
    print(f"Listening on: {', '.join(ifaces)}")
    print("Headers only (IPs, ports, protocol, size, flags). Ctrl+C to stop.")

    buffer = []

    def on_packet(pkt):
        doc = packet_to_doc(pkt)
        if doc is None:
            return
        buffer.append(doc)
        print(
            f"{doc['protocol']:5} {doc['src_ip']}:{doc['src_port']} -> "
            f"{doc['dst_ip']}:{doc['dst_port']}  {doc['bytes']}B  {doc['flags']}"
        )
        if len(buffer) >= BULK_SIZE:
            sent = flush_docs(buffer)
            if sent:
                print(f"Indexed {sent} packets into `{LOGS_INDEX}`")
            buffer.clear()

    try:
        while True:
            sniff(
                iface=ifaces,
                prn=on_packet,
                store=False,
                timeout=SNIFF_TIMEOUT_SEC,
            )
            if buffer:
                sent = flush_docs(buffer)
                if sent:
                    print(f"Indexed {sent} packets into `{LOGS_INDEX}`")
                buffer.clear()
            time.sleep(0.05)
    except KeyboardInterrupt:
        if buffer:
            flush_docs(buffer)
        print("\nStopped capture.")


if __name__ == "__main__":
    main()
