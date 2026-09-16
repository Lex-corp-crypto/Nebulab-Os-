"""
Agent Service for NebulaLab (Distributed Linux Lab)
S'exécute sur chaque machine (Pop!_OS, Ubuntu, Android Termux, Raspberry Pi, etc.)
Fonctionnalités :
1. Découverte automatique du Master API (mDNS / UDP broadcast)
2. Collecte temps réel CPU / RAM / Disque / Réseau / Charge / Docker
3. Exécution distante de commandes shell, scripts bash/python et conteneurs Docker
4. Centralisation des logs et transmission sécurisée
"""

import os
import sys
import json
import time
import socket
import logging
import asyncio
import platform
import subprocess
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import psutil
import aiohttp

# Import des modules locaux
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from service_discovery import ServiceDiscovery

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] [Agent] %(message)s')
logger = logging.getLogger("nebulalab.agent")


class AgentService:
    def __init__(self):
        self.hostname = os.getenv("HOSTNAME") or socket.gethostname()
        self.ip_address = self._get_local_ip()
        self.os_type = self._detect_os()
        self.agent_tags = os.getenv("AGENT_TAGS", "")

        # Spécifications de la machine
        self.cpu_cores = psutil.cpu_count(logical=True) or 1
        self.ram_total_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
        self.root_path = 'C:\\' if platform.system().lower() == 'windows' else '/'
        try:
            self.disk_total_gb = round(psutil.disk_usage(self.root_path).total / (1024 ** 3), 2)
        except Exception:
            self.disk_total_gb = 0.0

        # Configuration Master API
        self.api_url = os.getenv("API_URL", "").rstrip("/")
        self.metrics_interval = int(os.getenv("METRICS_INTERVAL", "5"))
        self.heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", "10"))
        self.job_poll_interval = int(os.getenv("JOB_POLL_INTERVAL", "2"))

        # État
        self.machine_id: Optional[int] = None
        self.registered = False
        self.running = False
        
        # Réseau I/O tracking
        self.last_net_io = psutil.net_io_counters()
        self.last_net_time = time.time()

        # Service discovery
        self.discovery = ServiceDiscovery(
            role="agent",
            service_port=8001,
            extra_info={"os": self.os_type, "cores": self.cpu_cores, "ram": self.ram_total_gb}
        )

    def _get_session(self, timeout_sec: float = 5.0) -> aiohttp.ClientSession:
        connector = aiohttp.TCPConnector(ssl=False)
        return aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=timeout_sec))

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _detect_os(self) -> str:
        """Détecte précisément le système : Pop!_OS, Ubuntu, Android, Windows, macOS, etc."""
        # Check Android (Termux)
        if "ANDROID_ROOT" in os.environ or os.path.exists("/system/build.prop"):
            return "Android"

        sys_name = platform.system()
        if sys_name.lower() == "windows":
            return f"Windows {platform.release()}"
        if sys_name.lower() == "darwin":
            return "macOS"

        if sys_name.lower() == "linux":
            try:
                if os.path.exists("/etc/os-release"):
                    with open("/etc/os-release", "r") as f:
                        content = f.read().lower()
                        if "pop" in content:
                            return "Pop!_OS"
                        elif "ubuntu" in content:
                            return "Ubuntu"
                        elif "debian" in content:
                            return "Debian"
                        elif "fedora" in content:
                            return "Fedora"
                        elif "arch" in content:
                            return "Arch Linux"
                        elif "raspbian" in content or "raspberry" in content:
                            return "Raspberry Pi OS"
            except Exception:
                pass
            return "Linux"
        return sys_name

    async def auto_discover_master(self) -> Optional[str]:
        """Tente de découvrir automatiquement l'URL du Master sur le LAN"""
        logger.info("🔍 Recherche automatique du Master API sur le réseau local...")
        
        # 1. Essayer UDP Broadcast instantané
        master_url = await self.discovery.discover_master_via_udp(timeout=2.0)
        if master_url:
            return master_url

        # 2. Essayer mDNS
        if self.discovery.master_info:
            m = self.discovery.master_info
            return f"http://{m['ip_address']}:{m['port']}"

        # 3. Fallbacks par défaut
        fallbacks = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://192.168.1.1:8000",
            "http://192.168.0.1:8000"
        ]
        for url in fallbacks:
            try:
                async with self._get_session(timeout_sec=1.5) as session:
                    async with session.get(f"{url}/health") as resp:
                        if resp.status == 200:
                            logger.info(f"Master API local trouvé sur {url}")
                            return url
            except Exception:
                pass
        return None

    async def register_with_api(self) -> bool:
        """Enregistre le nœud auprès du Master API"""
        if not self.api_url:
            discovered = await self.auto_discover_master()
            if discovered:
                self.api_url = discovered
            else:
                logger.warning("Impossible de joindre le Master API. Nouvelle tentative dans 5s...")
                return False

        payload = {
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "os_type": self.os_type,
            "cpu_cores": self.cpu_cores,
            "ram_total_gb": self.ram_total_gb,
            "disk_total_gb": self.disk_total_gb,
            "tags": self.agent_tags
        }

        try:
            async with self._get_session(timeout_sec=6.0) as session:
                async with session.post(f"{self.api_url}/api/machines/register", json=payload) as resp:
                    if resp.status in [200, 201]:
                        data = await resp.json()
                        self.machine_id = data["id"]
                        self.registered = True
                        logger.info(f"✅ Nœud enregistré avec succès ! Machine ID: #{self.machine_id} ({self.hostname} - {self.os_type})")
                        
                        # Envoyer un log de démarrage au Master
                        await self.send_log("INFO", f"Agent NebulaLab démarré sur {self.hostname} ({self.os_type})")
                        return True
                    else:
                        text = await resp.text()
                        logger.error(f"Échec enregistrement ({resp.status}) : {text}")
        except Exception as e:
            logger.error(f"Erreur connexion Master API ({self.api_url}) : {e}")
            # Reset api_url seulement si non configuré explicitement et pas de tunnel
            if not os.getenv("API_URL") and not self.api_url.startswith("https://"):
                self.api_url = ""
        return False

    async def send_heartbeat(self):
        """Envoie le heartbeat régulier"""
        if not self.registered or not self.machine_id:
            return
        try:
            async with self._get_session(timeout_sec=3.0) as session:
                async with session.put(f"{self.api_url}/api/machines/{self.machine_id}/heartbeat") as resp:
                    if resp.status != 200:
                        logger.debug(f"Heartbeat status non-200 : {resp.status}")
        except Exception as e:
            logger.debug(f"Erreur heartbeat : {e}")

    async def collect_and_send_metrics(self):
        """Collecte toutes les métriques de la machine et les envoie au Master"""
        if not self.registered or not self.machine_id:
            return

        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            try:
                disk = psutil.disk_usage(self.root_path)
                disk_pct = disk.percent
            except Exception:
                disk_pct = 0.0

            # Calculer la vitesse réseau en Ko/s
            now = time.time()
            net_io = psutil.net_io_counters()
            time_delta = max(0.1, now - self.last_net_time)
            rx_sec = round((net_io.bytes_recv - self.last_net_io.bytes_recv) / 1024 / time_delta, 1)
            tx_sec = round((net_io.bytes_sent - self.last_net_io.bytes_sent) / 1024 / time_delta, 1)
            self.last_net_io = net_io
            self.last_net_time = now

            # Load average
            try:
                load_avg = psutil.getloadavg()[0]
            except Exception:
                load_avg = 0.0

            metrics_payload = {
                "machine_id": self.machine_id,
                "cpu_percent": cpu_pct,
                "memory_percent": mem.percent,
                "disk_percent": disk_pct,
                "network_rx_sec": rx_sec,
                "network_tx_sec": tx_sec,
                "load_avg": round(load_avg, 2),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            async with self._get_session(timeout_sec=4.0) as session:
                async with session.post(f"{self.api_url}/api/metrics", json=metrics_payload) as resp:
                    if resp.status not in [200, 201]:
                        logger.debug(f"Échec envoi métriques ({resp.status})")
        except Exception as e:
            logger.debug(f"Erreur collecte métriques : {e}")

    async def poll_and_execute_jobs(self):
        """Récupère et exécute les jobs en attente assignés à ce nœud"""
        if not self.registered or not self.machine_id:
            return

        try:
            async with self._get_session(timeout_sec=5.0) as session:
                async with session.get(f"{self.api_url}/api/agent/{self.machine_id}/jobs/poll") as resp:
                    if resp.status == 200:
                        pending_jobs = await resp.json()
                        for job in pending_jobs:
                            asyncio.create_task(self.run_single_job(job))
        except Exception as e:
            logger.debug(f"Erreur poll jobs : {e}")

    async def run_single_job(self, job: dict):
        """Exécute un job (Shell, Script ou Docker) et transmet les résultats"""
        job_id = job["id"]
        command = job.get("command", "")
        arguments = job.get("arguments", [])
        script = job.get("script", "")
        job_type = job.get("job_type", "shell")
        
        logger.info(f"▶️ Démarrage Job #{job_id} [{job_type}] : {command} {' '.join(arguments) if arguments else ''}")

        # 1. Signaler que le job a démarré
        await self._update_job_status(job_id, "running")

        stdout_res = ""
        stderr_res = ""
        return_code = 0
        status_str = "completed"

        try:
            if job_type == "docker" or command.startswith("docker"):
                # Exécution Docker
                stdout_res, stderr_res, return_code = await self._execute_docker_job(command, arguments)
            elif job_type == "script" or script:
                # Exécution d'un script complet
                stdout_res, stderr_res, return_code = await self._execute_script_job(script, command)
            else:
                # Exécution de commande shell standard
                stdout_res, stderr_res, return_code = await self._execute_shell_job(command, arguments)

            status_str = "completed" if return_code == 0 else "failed"
        except Exception as e:
            status_str = "failed"
            stderr_res = f"Erreur fatale lors de l'exécution du job : {str(e)}"
            return_code = -1

        logger.info(f"🏁 Fin Job #{job_id} -> {status_str} (Code: {return_code})")
        await self._update_job_status(job_id, status_str, stdout_res, stderr_res, return_code)

    async def _execute_shell_job(self, command: str, arguments: list) -> tuple:
        """Exécute une commande shell avec timeout"""
        full_cmd = command
        if arguments:
            full_cmd = f"{command} " + " ".join(arguments)

        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            return (
                stdout_data.decode('utf-8', errors='replace'),
                stderr_data.decode('utf-8', errors='replace'),
                proc.returncode
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ("", "Timeout de la tâche après 120 secondes", -1)

    async def _execute_script_job(self, script_content: str, interpreter: str = "bash") -> tuple:
        """Écrit et exécute un script temporaire"""
        import tempfile
        ext = ".py" if "python" in interpreter else ".sh"
        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as f:
            f.write(script_content)
            tmp_path = f.name

        try:
            os.chmod(tmp_path, 0o755)
            cmd = f"{interpreter} {tmp_path}" if interpreter else f"bash {tmp_path}"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=300.0)
            return (
                stdout_data.decode('utf-8', errors='replace'),
                stderr_data.decode('utf-8', errors='replace'),
                proc.returncode
            )
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    async def _execute_docker_job(self, command: str, arguments: list) -> tuple:
        """Exécute une commande via Docker CLI ou Docker SDK"""
        if command == "docker_run" and arguments:
            image = arguments[0]
            cmd_inside = " ".join(arguments[1:]) if len(arguments) > 1 else ""
            docker_cmd = f"docker run --rm {image} {cmd_inside}"
        else:
            docker_cmd = f"{command} " + " ".join(arguments)

        proc = await asyncio.create_subprocess_shell(
            docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=300.0)
            return (
                stdout_data.decode('utf-8', errors='replace'),
                stderr_data.decode('utf-8', errors='replace'),
                proc.returncode
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return ("", "Timeout de l'exécution Docker après 300 secondes", -1)

    async def _update_job_status(self, job_id: int, status: str, stdout: str = "", stderr: str = "", return_code: int = 0):
        try:
            payload = {
                "status": status,
                "stdout": stdout,
                "stderr": stderr,
                "return_code": return_code
            }
            async with self._get_session(timeout_sec=10.0) as session:
                await session.post(
                    f"{self.api_url}/api/agent/{self.machine_id}/jobs/{job_id}/status",
                    json=payload
                )
        except Exception as e:
            logger.error(f"Erreur mise à jour statut job #{job_id} : {e}")

    async def send_log(self, level: str, message: str):
        """Transmet un log au Master pour centralisation"""
        if not self.registered or not self.machine_id or not self.api_url:
            return
        try:
            payload = {
                "machine_id": self.machine_id,
                "level": level,
                "source": self.hostname,
                "message": message
            }
            async with self._get_session(timeout_sec=3.0) as session:
                async with session.post(f"{self.api_url}/api/logs", json=payload) as resp:
                    await resp.read()
        except Exception:
            pass

    async def run(self):
        """Boucle principale du service Agent"""
        self.running = True
        logger.info(f"🚀 Démarrage de l'agent NebulaLab sur {self.hostname} ({self.os_type} - {self.ip_address})")
        
        # Initialiser discovery
        await self.discovery.initialize()

        # Boucle d'enregistrement initiale
        while self.running and not self.registered:
            registered = await self.register_with_api()
            if registered:
                break
            await asyncio.sleep(4)

        logger.info("⚡ Agent connecté au cluster avec succès !")

        # Boucles de fond
        metrics_task = asyncio.create_task(self._metrics_loop())
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        jobs_task = asyncio.create_task(self._jobs_loop())

        try:
            await asyncio.gather(metrics_task, heartbeat_task, jobs_task)
        except asyncio.CancelledError:
            logger.info("Arrêt de l'agent")
        finally:
            self.running = False
            self.discovery.stop()

    async def _metrics_loop(self):
        while self.running:
            await self.collect_and_send_metrics()
            await asyncio.sleep(self.metrics_interval)

    async def _heartbeat_loop(self):
        while self.running:
            await self.send_heartbeat()
            await asyncio.sleep(self.heartbeat_interval)

    async def _jobs_loop(self):
        while self.running:
            await self.poll_and_execute_jobs()
            await asyncio.sleep(self.job_poll_interval)

    def stop(self):
        self.running = False
        self.discovery.stop()


if __name__ == "__main__":
    agent = AgentService()
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logger.info("Arrêt utilisateur de l'agent")
        agent.stop()
    except Exception as e:
        logger.error(f"Erreur fatale de l'agent : {e}")
        sys.exit(1)