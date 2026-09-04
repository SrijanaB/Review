"""
Generate odd-looking traffic on THIS laptop only (127.0.0.1).

Why: Isolation Forest needs a few outliers during a demo. Normal browsing
looks mostly normal. These bursts stay on loopback — they never leave the
machine and never scan the campus or other phones.

live_capture.py also listens on lo0 so these packets are ingested.
"""

import argparse
import socket
import sys
from concurrent.futures import ThreadPoolExecutor

LOCALHOST = "127.0.0.1"


def scan_local_ports(start: int, end: int) -> None:
    """Many destination ports in a few seconds — one anomalous 10s window."""
    print(
        f"TCP connect burst to {LOCALHOST} ports {start}-{end} "
        "(expected: mostly refused)"
    )

    def hit(port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.05)
        try:
            sock.connect((LOCALHOST, port))
        except OSError:
            pass
        finally:
            sock.close()

    with ThreadPoolExecutor(max_workers=64) as pool:
        list(pool.map(hit, range(start, end + 1)))


def udp_scan_local(count: int, base_port: int) -> None:
    """UDP to many dest ports so unique_dst_ports spikes even if TCP SYNs are sparse."""
    print(f"UDP scan: {count} packets to {LOCALHOST}:{base_port}-{base_port + count - 1}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = b"x" * 16
    try:
        for i in range(count):
            sock.sendto(payload, (LOCALHOST, base_port + i))
    finally:
        sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Localhost-only demo traffic for SHIELD (never scans other hosts)."
    )
    parser.add_argument(
        "--mode",
        choices=("scan", "flood", "both"),
        default="both",
        help="scan = many local TCP ports; flood = many UDP dest ports",
    )
    parser.add_argument("--start-port", type=int, default=1)
    parser.add_argument("--end-port", type=int, default=400)
    parser.add_argument("--flood-count", type=int, default=400)
    parser.add_argument("--flood-port", type=int, default=20000)
    args = parser.parse_args()

    if args.start_port < 1 or args.end_port > 65535 or args.start_port > args.end_port:
        print("Port range must be 1-65535 and start <= end.")
        sys.exit(1)

    print(f"Target is always {LOCALHOST}. Nothing is sent to the Wi-Fi LAN.")
    if args.mode in ("scan", "both"):
        scan_local_ports(args.start_port, args.end_port)
    if args.mode in ("flood", "both"):
        udp_scan_local(args.flood_count, args.flood_port)
    print("Done. Wait one completed 10s window, then check Kibana for a port-count spike.")


if __name__ == "__main__":
    main()
