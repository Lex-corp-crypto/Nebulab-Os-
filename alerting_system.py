"""
Alerting System for NebulaLab (Distributed Linux Lab)
Surveille les métriques système et l'état des nœuds, déclenche des alertes et envoie des notifications.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.alerts")


class AlertingSystem:
    def __init__(self, db_manager, websocket_manager=None):
        self.db_manager = db_manager
        self.websocket_manager = websocket_manager

        # Seuils configurables (pourcentages)
        self.thresholds = {
            "cpu_warning": float(os.getenv("CPU_WARNING_THRESHOLD", "80.0")),
            "cpu_critical": float(os.getenv("CPU_CRITICAL_THRESHOLD", "95.0")),
            "memory_warning": float(os.getenv("MEMORY_WARNING_THRESHOLD", "80.0")),
            "memory_critical": float(os.getenv("MEMORY_CRITICAL_THRESHOLD", "95.0")),
            "disk_warning": float(os.getenv("DISK_WARNING_THRESHOLD", "85.0")),
            "disk_critical": float(os.getenv("DISK_CRITICAL_THRESHOLD", "95.0")),
            "offline_timeout_sec": int(os.getenv("OFFLINE_TIMEOUT_SEC", "60"))
        }

        # Notifications
        self.email_enabled = os.getenv("EMAIL_ALERTS_ENABLED", "false").lower() == "true"
        self.webhook_enabled = os.getenv("WEBHOOK_ALERTS_ENABLED", "false").lower() == "true"
        self.webhook_url = os.getenv("WEBHOOK_URL", "")

        # Anti-spam cooldown (par machine et type d'alerte)
        self.alert_cooldown: Dict[tuple, datetime] = {}
        self.cooldown_period = timedelta(minutes=int(os.getenv("ALERT_COOLDOWN_MINUTES", "10")))

    async def check_metrics_and_alert(self, machine_id: int, cpu_percent: float,
                                    memory_percent: float, disk_percent: float):
        """Évalue les métriques reçues d'un agent et génère des alertes si les seuils sont dépassés"""
        machine = await self.db_manager.get_machine(machine_id)
        hostname = machine.get("hostname", f"Node-{machine_id}") if machine else f"Node-{machine_id}"

        # 1. CPU
        if cpu_percent >= self.thresholds["cpu_critical"]:
            await self._trigger_alert(machine_id, hostname, "cpu", "critical", f"CPU Critique sur {hostname} : {cpu_percent:.1f}%", cpu_percent)
        elif cpu_percent >= self.thresholds["cpu_warning"]:
            await self._trigger_alert(machine_id, hostname, "cpu", "warning", f"CPU Élevé sur {hostname} : {cpu_percent:.1f}%", cpu_percent)

        # 2. Mémoire
        if memory_percent >= self.thresholds["memory_critical"]:
            await self._trigger_alert(machine_id, hostname, "memory", "critical", f"RAM Critique sur {hostname} : {memory_percent:.1f}%", memory_percent)
        elif memory_percent >= self.thresholds["memory_warning"]:
            await self._trigger_alert(machine_id, hostname, "memory", "warning", f"RAM Élevée sur {hostname} : {memory_percent:.1f}%", memory_percent)

        # 3. Disque
        if disk_percent >= self.thresholds["disk_critical"]:
            await self._trigger_alert(machine_id, hostname, "disk", "critical", f"Espace disque critique sur {hostname} : {disk_percent:.1f}%", disk_percent)
        elif disk_percent >= self.thresholds["disk_warning"]:
            await self._trigger_alert(machine_id, hostname, "disk", "warning", f"Espace disque faible sur {hostname} : {disk_percent:.1f}%", disk_percent)

    async def check_offline_nodes(self):
        """Vérifie si des machines ne répondent plus (heartbeat expiré)"""
        try:
            machines = await self.db_manager.get_all_machines()
            now = datetime.now(timezone.utc)
            for m in machines:
                last_seen = m.get("last_seen")
                if isinstance(last_seen, str):
                    try:
                        last_seen = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                    except Exception:
                        continue
                if isinstance(last_seen, datetime):
                    if last_seen.tzinfo is None:
                        last_seen = last_seen.replace(tzinfo=timezone.utc)
                    diff_sec = (now - last_seen).total_seconds()
                    if diff_sec > self.thresholds["offline_timeout_sec"]:
                        if m.get("is_active"):
                            # Marquer inactif
                            await self.db_manager._execute("UPDATE machines SET is_active = $1 WHERE id = $2", False, m["id"])
                            await self._trigger_alert(
                                m["id"], m["hostname"], "node_offline", "critical",
                                f"Nœud {m['hostname']} hors-ligne (pas de réponse depuis {int(diff_sec)}s)", diff_sec
                            )
        except Exception as e:
            logger.error(f"Erreur lors du check des nœuds hors-ligne : {e}")

    async def _trigger_alert(self, machine_id: int, hostname: str, alert_type: str, severity: str, message: str, value: float):
        """Génère l'alerte, enregistre en base et diffuse sur WebSocket + Webhook"""
        key = (machine_id, alert_type, severity)
        now = datetime.now(timezone.utc)
        if key in self.alert_cooldown:
            if now - self.alert_cooldown[key] < self.cooldown_period:
                return

        self.alert_cooldown[key] = now

        alert_data = {
            "machine_id": machine_id,
            "alert_type": alert_type,
            "severity": severity,
            "message": message,
            "value": value
        }
        saved_alert = await self.db_manager.create_alert(alert_data)
        logger.warning(f"🚨 ALERTE [{severity.upper()}] {message}")

        # Diffusion temps réel sur WebSocket (pour mise à jour instantanée du dashboard / téléphone)
        if self.websocket_manager:
            await self.websocket_manager.broadcast_json({
                "type": "alert_triggered",
                "alert": saved_alert,
                "hostname": hostname
            })

        # Webhook (Discord / Slack / ntfy / custom)
        if self.webhook_enabled and self.webhook_url:
            asyncio.create_task(self._send_webhook(saved_alert, hostname))

    async def _send_webhook(self, alert: dict, hostname: str):
        try:
            payload = {
                "title": f"🚨 [NebulaLab Alert] {alert.get('severity', '').upper()} - {hostname}",
                "description": alert.get("message", ""),
                "fields": [
                    {"name": "Nœud", "value": hostname, "inline": True},
                    {"name": "Type", "value": alert.get("alert_type", ""), "inline": True},
                    {"name": "Sévérité", "value": alert.get("severity", ""), "inline": True},
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            async with aiohttp.ClientSession() as session:
                await session.post(self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=5))
        except Exception as e:
            logger.error(f"Échec envoi notification Webhook : {e}")

    async def get_active_alerts(self) -> List[dict]:
        return await self.db_manager.get_unresolved_alerts()

    async def resolve_alert(self, alert_id: int):
        await self.db_manager.resolve_alert(alert_id)
        if self.websocket_manager:
            await self.websocket_manager.broadcast_json({
                "type": "alert_resolved",
                "alert_id": alert_id
            })

    async def resolve_all_alerts(self):
        await self.db_manager.resolve_all_alerts()
        if self.websocket_manager:
            await self.websocket_manager.broadcast_json({
                "type": "all_alerts_resolved"
            })