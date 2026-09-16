"""
Webhook Notifier supporting Discord, Slack, Telegram, ntfy.sh and custom webhooks.
"""
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any
import aiohttp

logger = logging.getLogger("nebulalab.alerts.webhook")


class WebhookNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_alert(self, alert: Dict[str, Any], hostname: str):
        if not self.webhook_url:
            return

        severity = alert.get("severity", "warning").upper()
        color = 0xff0000 if severity == "CRITICAL" else 0xffaa00

        # Discord / Slack compatible payload
        payload = {
            "content": f"🚨 **[NebulaLab Alert]** {severity} sur `{hostname}`",
            "embeds": [
                {
                    "title": f"Alerte Système : {alert.get('alert_type', '').upper()}",
                    "description": alert.get("message", ""),
                    "color": color,
                    "fields": [
                        {"name": "Nœud", "value": hostname, "inline": True},
                        {"name": "Sévérité", "value": severity, "inline": True},
                        {"name": "Valeur", "value": f"{alert.get('value', 0):.1f}%", "inline": True}
                    ],
                    "timestamp": datetime.utcnow().isoformat()
                }
            ]
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status in [200, 204]:
                        logger.info(f"Notification Webhook transmise avec succès pour {hostname}")
        except Exception as e:
            logger.debug(f"Erreur envoi notification Webhook : {e}")
