"""
Hardware and OS Telemetry Collector for NebulaLab Agents.
Collecte l'utilisation CPU globale et par cœur, la RAM, les disques, les E/S réseau et la charge.
"""
import time
import psutil
from typing import Dict, Any, List


class TelemetryCollector:
    def __init__(self):
        self.last_net = psutil.net_io_counters()
        self.last_time = time.time()

    def collect(self, machine_id: int) -> Dict[str, Any]:
        """Collecte un snapshot complet des ressources"""
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        
        mem = psutil.virtual_memory()
        
        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
        except Exception:
            disk_percent = 0.0

        # Réseau
        now = time.time()
        curr_net = psutil.net_io_counters()
        dt = max(0.1, now - self.last_time)
        rx_sec = round((curr_net.bytes_recv - self.last_net.bytes_recv) / 1024 / dt, 1)
        tx_sec = round((curr_net.bytes_sent - self.last_net.bytes_sent) / 1024 / dt, 1)
        self.last_net = curr_net
        self.last_time = now

        # Load average
        try:
            load_avg = psutil.getloadavg()[0]
        except Exception:
            load_avg = 0.0

        return {
            "machine_id": machine_id,
            "cpu_percent": cpu_percent,
            "cpu_per_core": cpu_per_core,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024 ** 3), 2),
            "memory_total_gb": round(mem.total / (1024 ** 3), 2),
            "disk_percent": disk_percent,
            "network_rx_sec": rx_sec,
            "network_tx_sec": tx_sec,
            "load_avg": round(load_avg, 2)
        }
