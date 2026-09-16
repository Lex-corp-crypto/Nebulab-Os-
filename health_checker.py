"""
Health Checker for NebulaLab (Distributed Linux Lab)
Fournit des contrôles de santé complets pour tous les composants du système (API, DB, Redis, Système).
"""

import os
import logging
import asyncio
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
import psutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.health")


class HealthChecker:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.start_time = time.time()
        self.timeout = int(os.getenv('HEALTH_CHECK_TIMEOUT', '5'))

    async def check_database_health(self) -> Dict[str, Any]:
        """Vérifie la santé de la base de données (PostgreSQL ou SQLite)"""
        start_time = time.time()
        try:
            # Test simple de requête
            machines = await self.db_manager.get_all_machines()
            response_time = (time.time() - start_time) * 1000  # ms

            db_type = "sqlite" if self.db_manager.is_sqlite else "postgresql"
            return {
                'status': 'healthy',
                'response_time_ms': round(response_time, 2),
                'details': {
                    'engine': db_type,
                    'node_records': len(machines)
                }
            }
        except Exception as e:
            logger.error(f"Échec health check base de données : {e}")
            return {
                'status': 'unhealthy',
                'response_time_ms': round((time.time() - start_time) * 1000, 2),
                'details': {
                    'error': str(e)
                }
            }

    async def check_system_resources(self) -> Dict[str, Any]:
        """Vérifie les ressources système de la machine hôte"""
        start_time = time.time()
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            try:
                disk = psutil.disk_usage('/')
                disk_percent = disk.percent
            except Exception:
                disk_percent = 0.0

            status = 'healthy'
            if cpu_percent > 95 or memory.percent > 95 or disk_percent > 95:
                status = 'unhealthy'
            elif cpu_percent > 80 or memory.percent > 85 or disk_percent > 85:
                status = 'degraded'

            response_time = (time.time() - start_time) * 1000

            return {
                'status': status,
                'response_time_ms': round(response_time, 2),
                'details': {
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'disk_percent': disk_percent,
                    'cores': psutil.cpu_count(logical=True)
                }
            }
        except Exception as e:
            return {
                'status': 'unknown',
                'details': {'error': str(e)}
            }

    async def run_all_health_checks(self) -> Dict[str, Any]:
        """Exécute l'ensemble des diagnostics"""
        start_time = time.time()
        db_res, sys_res = await asyncio.gather(
            self.check_database_health(),
            self.check_system_resources(),
            return_exceptions=True
        )

        checks = {
            'database': db_res if not isinstance(db_res, Exception) else {'status': 'unhealthy', 'error': str(db_res)},
            'system': sys_res if not isinstance(sys_res, Exception) else {'status': 'unhealthy', 'error': str(sys_res)}
        }

        overall = 'healthy'
        if any(c.get('status') == 'unhealthy' for c in checks.values()):
            overall = 'unhealthy'
        elif any(c.get('status') == 'degraded' for c in checks.values()):
            overall = 'degraded'

        return {
            'status': overall,
            'timestamp': datetime.utcnow().isoformat(),
            'total_response_time_ms': round((time.time() - start_time) * 1000, 2),
            'uptime_seconds': round(time.time() - self.start_time, 1),
            'checks': checks
        }