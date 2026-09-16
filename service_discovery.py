"""
Service Discovery for NebulaLab (Distributed Linux Lab)
Assure la découverte automatique des nœuds sur le réseau local via :
1. mDNS / Zeroconf (standard IETF)
2. UDP Broadcast Fallback (idéal pour les box/routeurs Wi-Fi domestiques)
"""

import os
import json
import socket
import logging
import asyncio
from typing import List, Dict, Any, Optional
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceListener

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.discovery")

UDP_BROADCAST_PORT = 5354
MDNS_SERVICE_TYPE = "_nebulalab._tcp.local."


class ServiceDiscovery(ServiceListener):
    def __init__(self, role: str = "agent", service_port: int = 8000, extra_info: Optional[Dict[str, Any]] = None):
        self.role = role
        self.hostname = os.getenv("HOSTNAME") or socket.gethostname().split(".")[0]
        self.ip_address = self._get_local_ip()
        self.service_port = service_port
        self.extra_info = extra_info or {}
        
        self.zeroconf: Optional[Zeroconf] = None
        self.browser: Optional[ServiceBrowser] = None
        self.discovered_peers: Dict[str, Dict[str, Any]] = {}
        self.master_info: Optional[Dict[str, Any]] = None
        self.running = False

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def initialize(self):
        """Initialise Zeroconf en tâche d'arrière-plan sans bloquer"""
        logger.info(f"Démarrage Service Discovery ({self.role}) sur {self.ip_address}:{self.service_port}")
        self.running = True
        asyncio.create_task(self._init_zeroconf_async())

    async def _init_zeroconf_async(self):
        try:
            self.zeroconf = await asyncio.to_thread(Zeroconf)
            await self._register_service_async()
            self.browser = await asyncio.to_thread(ServiceBrowser, self.zeroconf, MDNS_SERVICE_TYPE, self)
            logger.info("Découverte Zeroconf active")
        except Exception as e:
            logger.debug(f"Zeroconf initialisation non critique : {e}")

    async def _register_service_async(self):
        if not self.zeroconf:
            return
        desc = {
            'role': self.role,
            'hostname': self.hostname,
            'ip': self.ip_address,
            'port': str(self.service_port),
            'version': '2.0.0'
        }
        desc.update({k: str(v) for k, v in self.extra_info.items()})

        service_name = f"{self.hostname}-{self.role}.{MDNS_SERVICE_TYPE}"
        try:
            info = ServiceInfo(
                MDNS_SERVICE_TYPE,
                service_name,
                addresses=[socket.inet_aton(self.ip_address)],
                port=self.service_port,
                properties=desc,
                server=f"{self.hostname}.local."
            )
            await asyncio.to_thread(self.zeroconf.register_service, info)
            logger.info(f"Service mDNS annoncé : {service_name}")
        except Exception as e:
            logger.debug(f"Avis mDNS (fallback UDP actif) : {e}")

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        try:
            info = zc.get_service_info(type_, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                props = {
                    (k.decode('utf-8') if isinstance(k, bytes) else k):
                    (v.decode('utf-8') if isinstance(v, bytes) else v)
                    for k, v in info.properties.items()
                }
                peer = {
                    "name": name,
                    "hostname": props.get("hostname", name.split(".")[0]),
                    "role": props.get("role", "agent"),
                    "ip_address": ip,
                    "port": info.port,
                    "properties": props
                }
                key = f"{ip}:{info.port}"
                self.discovered_peers[key] = peer
                if peer["role"] == "master":
                    self.master_info = peer
                logger.info(f"[Discovery mDNS] Nœud détecté : {peer['hostname']} ({peer['role']}) sur {ip}:{info.port}")
        except Exception:
            pass

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        to_remove = [k for k, v in self.discovered_peers.items() if v.get("name") == name]
        for k in to_remove:
            removed = self.discovered_peers.pop(k, None)
            if removed:
                logger.info(f"[Discovery mDNS] Nœud déconnecté : {removed.get('hostname')}")

    async def run_udp_broadcast_responder(self):
        """Le Master écoute les pings de découverte et répond avec son IP"""
        loop = asyncio.get_running_loop()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", UDP_BROADCAST_PORT))
            sock.setblocking(False)

            logger.info(f"Écoute UDP Broadcast sur le port {UDP_BROADCAST_PORT}")
            while self.running:
                try:
                    data, addr = await loop.sock_recvfrom(sock, 1024)
                    message = data.decode('utf-8', errors='ignore')
                    if "NEBULALAB_DISCOVERY_PING" in message:
                        response = json.dumps({
                            "type": "NEBULALAB_DISCOVERY_PONG",
                            "role": self.role,
                            "hostname": self.hostname,
                            "ip": self.ip_address,
                            "port": self.service_port
                        }).encode('utf-8')
                        await loop.sock_sendto(sock, response, addr)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"UDP Broadcast Responder arrêté : {e}")

    async def discover_master_via_udp(self, timeout: float = 2.0) -> Optional[str]:
        """L'Agent envoie un ping broadcast UDP pour trouver le Master instantanément"""
        loop = asyncio.get_running_loop()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(timeout)
            
            ping = json.dumps({"type": "NEBULALAB_DISCOVERY_PING", "hostname": self.hostname}).encode('utf-8')
            sock.sendto(ping, ('<broadcast>', UDP_BROADCAST_PORT))
            
            sock.setblocking(False)
            data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=timeout)
            sock.close()
            
            res = json.loads(data.decode('utf-8'))
            if res.get("type") == "NEBULALAB_DISCOVERY_PONG":
                master_ip = res.get("ip", addr[0])
                master_port = res.get("port", 8000)
                url = f"http://{master_ip}:{master_port}"
                logger.info(f"[Discovery UDP] Master trouvé sur {url}")
                return url
        except Exception:
            pass
        return None

    async def get_discovered_peers(self) -> List[Dict[str, Any]]:
        return list(self.discovered_peers.values())

    def stop(self):
        self.running = False
        if self.zeroconf:
            try:
                self.zeroconf.close()
            except Exception:
                pass
        logger.info("Service Discovery arrêté")