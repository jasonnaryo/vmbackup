#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from urllib import error, request


COMMON_TIERS = [50, 100, 200, 300, 500, 1000, 2000, 5000, 10000]


@dataclass
class Snapshot:
    ts: float
    rx_bytes: int
    tx_bytes: int


class NetworkAgent:
    def __init__(self) -> None:
        self.report_url = os.getenv("REPORT_URL", "http://127.0.0.1:8080/telemetry")
        self.report_interval = float(os.getenv("REPORT_INTERVAL_SEC", "5"))
        self.sample_interval = float(os.getenv("SAMPLE_INTERVAL_SEC", "1"))
        self.host_id = os.getenv("HOST_ID", socket.gethostname())
        self.auth_token = os.getenv("AUTH_TOKEN")

        self.default_iface: Optional[str] = None
        self.gateway: Optional[str] = None
        self.link_speed_mbps: Optional[int] = None

        self.last_snapshot: Optional[Snapshot] = None
        self.last_report_ts = 0.0
        self.peak_upload_mbps = 0.0
        self.peak_download_mbps = 0.0

    def get_default_route(self) -> Tuple[Optional[str], Optional[str]]:
        try:
            output = subprocess.check_output(["ip", "route", "show", "default"], text=True).strip()
        except Exception:
            return None, None
        if not output:
            return None, None

        line = output.splitlines()[0]
        parts = line.split()
        gateway = None
        iface = None
        if "via" in parts:
            gateway = parts[parts.index("via") + 1]
        if "dev" in parts:
            iface = parts[parts.index("dev") + 1]
        return gateway, iface

    def get_interface_speed_mbps(self, iface: str) -> Optional[int]:
        speed_file = f"/sys/class/net/{iface}/speed"
        try:
            with open(speed_file, "r", encoding="utf-8") as f:
                v = int(f.read().strip())
                if v > 0:
                    return v
        except Exception:
            return None
        return None

    def read_proc_net_dev(self, iface: str) -> Tuple[int, int]:
        with open("/proc/net/dev", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith(f"{iface}:"):
                    continue
                data = line.split(":", 1)[1].split()
                rx_bytes = int(data[0])
                tx_bytes = int(data[8])
                return rx_bytes, tx_bytes
        raise RuntimeError(f"interface not found: {iface}")

    def infer_capacity_mbps(self, peak_down_mbps: float, link_speed_mbps: Optional[int]) -> int:
        candidate = peak_down_mbps * 1.25
        if link_speed_mbps:
            candidate = min(candidate, link_speed_mbps)
        if candidate <= 0:
            return 100
        return min(COMMON_TIERS, key=lambda x: abs(x - candidate))

    def infer_connection_type(self, link_speed_mbps: Optional[int], peak_down_mbps: float) -> str:
        if link_speed_mbps and link_speed_mbps >= 1000 and peak_down_mbps >= 100:
            return "fiber"
        if link_speed_mbps and link_speed_mbps >= 2500:
            return "fiber"
        return "broadband"

    def build_payload(self, snapshot: Snapshot, upload_bps: float, download_bps: float) -> Dict:
        upload_mbps = upload_bps * 8 / 1_000_000
        download_mbps = download_bps * 8 / 1_000_000

        self.peak_upload_mbps = max(self.peak_upload_mbps, upload_mbps)
        self.peak_download_mbps = max(self.peak_download_mbps, download_mbps)

        est_capacity = self.infer_capacity_mbps(self.peak_download_mbps, self.link_speed_mbps)
        conn_type = self.infer_connection_type(self.link_speed_mbps, self.peak_download_mbps)

        return {
            "host_id": self.host_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "network": {
                "default_interface": self.default_iface,
                "gateway": self.gateway,
                "link_speed_mbps": self.link_speed_mbps,
                "connection_type": conn_type,
                "estimated_gateway_capacity_mbps": est_capacity,
            },
            "rates": {
                "upload_bps": upload_bps,
                "download_bps": download_bps,
                "upload_mbps": round(upload_mbps, 3),
                "download_mbps": round(download_mbps, 3),
                "peak_upload_mbps": round(self.peak_upload_mbps, 3),
                "peak_download_mbps": round(self.peak_download_mbps, 3),
            },
            "counters": {
                "tx_bytes": snapshot.tx_bytes,
                "rx_bytes": snapshot.rx_bytes,
            },
        }

    def report(self, payload: Dict) -> None:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(self.report_url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=3) as resp:
                print(f"[report] ok {resp.status}")
        except error.URLError as exc:
            print(f"[report] failed: {exc}")

    def refresh_route(self) -> bool:
        gateway, iface = self.get_default_route()
        changed = gateway != self.gateway or iface != self.default_iface
        if changed:
            self.gateway = gateway
            self.default_iface = iface
            self.link_speed_mbps = self.get_interface_speed_mbps(iface) if iface else None
            self.last_snapshot = None
            print(
                "[route] gateway=%s iface=%s speed=%sMbps"
                % (self.gateway, self.default_iface, self.link_speed_mbps)
            )
        return changed

    def run(self) -> None:
        print("[agent] start")
        while True:
            self.refresh_route()
            if not self.default_iface:
                time.sleep(self.sample_interval)
                continue

            now = time.time()
            try:
                rx, tx = self.read_proc_net_dev(self.default_iface)
            except Exception as exc:
                print(f"[sample] failed: {exc}")
                time.sleep(self.sample_interval)
                continue

            cur = Snapshot(ts=now, rx_bytes=rx, tx_bytes=tx)
            if self.last_snapshot is None:
                self.last_snapshot = cur
                time.sleep(self.sample_interval)
                continue

            dt = max(cur.ts - self.last_snapshot.ts, 1e-6)
            download_bps = max((cur.rx_bytes - self.last_snapshot.rx_bytes) / dt, 0.0)
            upload_bps = max((cur.tx_bytes - self.last_snapshot.tx_bytes) / dt, 0.0)

            if now - self.last_report_ts >= self.report_interval:
                payload = self.build_payload(cur, upload_bps, download_bps)
                print(f"[telemetry] {json.dumps(payload, ensure_ascii=False)}")
                self.report(payload)
                self.last_report_ts = now

            self.last_snapshot = cur
            time.sleep(self.sample_interval)


if __name__ == "__main__":
    NetworkAgent().run()
