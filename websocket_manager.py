"""
WebSocket Manager for NebulaLab (Distributed Linux Lab)
Gère les flux temps réel bidirectionnels entre le Core API et les clients (Dashboard Web, Navigateur Mobile, CLI).
"""

import json
import logging
import asyncio
from typing import Set, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.websocket")


class WebSocketManager:
    def __init__(self):
        self.active_connections: Set[Any] = set()

    async def connect(self, websocket):
        """Accepte une nouvelle connexion WebSocket"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Nouveau client WebSocket connecté. Total connectés: {len(self.active_connections)}")
        
        # Envoyer un message de bienvenue
        await self.send_personal_json({
            "type": "welcome",
            "message": "Connecté au flux temps réel NebulaLab OS",
            "active_clients": len(self.active_connections)
        }, websocket)

    def disconnect(self, websocket):
        """Déconnecte un client"""
        self.active_connections.discard(websocket)
        logger.info(f"Client WebSocket déconnecté. Restants: {len(self.active_connections)}")

    async def send_personal_json(self, data: Dict[str, Any], websocket):
        """Envoie des données JSON à un client spécifique"""
        try:
            await websocket.send_text(json.dumps(data))
        except Exception as e:
            logger.debug(f"Erreur envoi personnel : {e}")
            self.disconnect(websocket)

    async def broadcast_json(self, data: Dict[str, Any]):
        """Diffuse un message JSON à tous les dashboards et téléphones connectés"""
        if not self.active_connections:
            return
        message = json.dumps(data)
        to_remove = set()
        
        for ws in list(self.active_connections):
            try:
                await ws.send_text(message)
            except Exception:
                to_remove.add(ws)

        for ws in to_remove:
            self.disconnect(ws)

    def get_connection_count(self) -> int:
        return len(self.active_connections)