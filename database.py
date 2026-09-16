"""
Database Manager for NebulaLab (Distributed Linux Lab)
Gère les connexions et opérations de base de données.
Supporte PostgreSQL (via asyncpg) et SQLite (via aiosqlite) pour un démarrage ultra-rapide.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.database")


class DatabaseManager:
    def __init__(self, connection_string: Optional[str] = None):
        self.connection_string = connection_string or os.getenv(
            "DATABASE_URL",
            "sqlite:///./data/nebulalab.db"
        )
        self.is_sqlite = self.connection_string.startswith("sqlite")
        self.pg_pool = None
        self.sqlite_db_path = None
        
        if self.is_sqlite:
            # Parse path: sqlite:///./data/nebulalab.db -> ./data/nebulalab.db
            raw_path = self.connection_string.replace("sqlite:///", "").replace("sqlite://", "")
            self.sqlite_db_path = os.path.abspath(raw_path)
            os.makedirs(os.path.dirname(self.sqlite_db_path), exist_ok=True)

    async def connect(self):
        """Établit la connexion à la base de données (PostgreSQL ou SQLite)"""
        try:
            if self.is_sqlite:
                import aiosqlite
                async with aiosqlite.connect(self.sqlite_db_path) as conn:
                    await conn.execute("PRAGMA journal_mode=WAL;")
                await self._create_tables()
                logger.info(f"Connexion SQLite établie sur {self.sqlite_db_path}")
            else:
                import asyncpg
                self.pg_pool = await asyncpg.create_pool(self.connection_string, min_size=2, max_size=10)
                await self._create_tables()
                logger.info("Connexion PostgreSQL établie")
        except Exception as e:
            logger.error(f"Erreur de connexion DB ({self.connection_string}) : {e}")
            if not self.is_sqlite:
                logger.warning("Basculement automatique sur SQLite local de secours...")
                self.is_sqlite = True
                self.sqlite_db_path = os.path.abspath("./data/nebulalab.db")
                os.makedirs(os.path.dirname(self.sqlite_db_path), exist_ok=True)
                await self._create_tables()
                logger.info(f"SQLite de secours activé sur {self.sqlite_db_path}")
            else:
                raise

    async def disconnect(self):
        """Ferme la connexion à la base de données"""
        if self.pg_pool:
            await self.pg_pool.close()
            logger.info("Connexion PostgreSQL fermée")

    async def _execute(self, query: str, *args):
        """Exécute une requête d'écriture / DDL de manière transparente pour PG et SQLite"""
        if self.is_sqlite:
            import aiosqlite
            sqlite_query = self._pg_to_sqlite_query(query)
            clean_args = [self._serialize_sqlite_arg(a) for a in args]
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                await conn.execute(sqlite_query, clean_args)
                await conn.commit()
        else:
            async with self.pg_pool.acquire() as conn:
                await conn.execute(query, *args)

    async def _fetchrow(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Récupère une seule ligne sous forme de dictionnaire"""
        if self.is_sqlite:
            import aiosqlite
            sqlite_query = self._pg_to_sqlite_query(query)
            clean_args = [self._serialize_sqlite_arg(a) for a in args]
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(sqlite_query, clean_args) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        else:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow(query, *args)
                return dict(row) if row else None

    async def _fetchall(self, query: str, *args) -> List[Dict[str, Any]]:
        """Récupère plusieurs lignes sous forme de dictionnaires"""
        if self.is_sqlite:
            import aiosqlite
            sqlite_query = self._pg_to_sqlite_query(query)
            clean_args = [self._serialize_sqlite_arg(a) for a in args]
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(sqlite_query, clean_args) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        else:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                return [dict(row) for row in rows]

    def _pg_to_sqlite_query(self, query: str) -> str:
        """Convertit la syntaxe PostgreSQL ($1, $2, RETURNING) pour SQLite"""
        import re
        q = re.sub(r'\$\d+', '?', query)
        q = q.replace('NOW()', "datetime('now')")
        q = q.replace('CURRENT_TIMESTAMP', "datetime('now')")
        q = q.replace('SERIAL PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT')
        q = q.replace('BOOLEAN DEFAULT TRUE', 'INTEGER DEFAULT 1')
        q = q.replace('BOOLEAN DEFAULT FALSE', 'INTEGER DEFAULT 0')
        q = q.replace('TEXT[]', 'TEXT')
        return q

    def _serialize_sqlite_arg(self, arg: Any) -> Any:
        if isinstance(arg, (list, dict)):
            return json.dumps(arg)
        if isinstance(arg, datetime):
            return arg.isoformat()
        if isinstance(arg, bool):
            return 1 if arg else 0
        return arg

    async def _create_tables(self):
        """Crée toutes les tables requises pour NebulaLab"""
        if self.is_sqlite:
            import aiosqlite
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                await conn.executescript('''
                    CREATE TABLE IF NOT EXISTS machines (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        hostname VARCHAR(255) NOT NULL,
                        ip_address VARCHAR(45) NOT NULL,
                        os_type VARCHAR(50) NOT NULL,
                        last_seen DATETIME NOT NULL,
                        is_active INTEGER DEFAULT 1,
                        cpu_cores INTEGER DEFAULT 1,
                        ram_total_gb REAL DEFAULT 0,
                        disk_total_gb REAL DEFAULT 0,
                        tags TEXT DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(hostname, ip_address)
                    );

                    CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        machine_id INTEGER REFERENCES machines(id),
                        command TEXT NOT NULL,
                        arguments TEXT DEFAULT '[]',
                        script TEXT DEFAULT '',
                        job_type VARCHAR(30) DEFAULT 'shell',
                        priority INTEGER DEFAULT 0,
                        status VARCHAR(20) DEFAULT 'pending',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        started_at DATETIME NULL,
                        completed_at DATETIME NULL,
                        stdout TEXT DEFAULT '',
                        stderr TEXT DEFAULT '',
                        return_code INTEGER DEFAULT 0,
                        created_by VARCHAR(100) DEFAULT 'admin'
                    );

                    CREATE TABLE IF NOT EXISTS metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        machine_id INTEGER REFERENCES machines(id),
                        cpu_percent REAL,
                        memory_percent REAL,
                        disk_percent REAL,
                        network_rx_sec REAL DEFAULT 0,
                        network_tx_sec REAL DEFAULT 0,
                        load_avg REAL DEFAULT 0,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS file_transfers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_machine_id INTEGER,
                        destination_machine_id INTEGER,
                        filename VARCHAR(255) NOT NULL,
                        file_path TEXT DEFAULT '',
                        size_bytes INTEGER DEFAULT 0,
                        checksum VARCHAR(64) DEFAULT '',
                        status VARCHAR(20) DEFAULT 'pending',
                        error_message TEXT DEFAULT '',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        completed_at DATETIME NULL
                    );

                    CREATE TABLE IF NOT EXISTS alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        machine_id INTEGER REFERENCES machines(id),
                        alert_type VARCHAR(50) NOT NULL,
                        severity VARCHAR(20) NOT NULL,
                        message TEXT NOT NULL,
                        value REAL DEFAULT 0,
                        is_resolved INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        resolved_at DATETIME NULL
                    );

                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username VARCHAR(100) UNIQUE NOT NULL,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        hashed_password VARCHAR(255) NOT NULL,
                        role VARCHAR(50) DEFAULT 'admin',
                        is_active INTEGER DEFAULT 1,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        last_login DATETIME NULL
                    );

                    CREATE TABLE IF NOT EXISTS system_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        machine_id INTEGER NULL,
                        level VARCHAR(20) DEFAULT 'INFO',
                        source VARCHAR(100) DEFAULT 'system',
                        message TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_machines_last_seen ON machines(last_seen);
                    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                    CREATE INDEX IF NOT EXISTS idx_metrics_machine_time ON metrics(machine_id, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(is_resolved);
                    CREATE INDEX IF NOT EXISTS idx_logs_time ON system_logs(timestamp);
                ''')
                await conn.commit()
        else:
            async with self.pg_pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS machines (
                        id SERIAL PRIMARY KEY,
                        hostname VARCHAR(255) NOT NULL,
                        ip_address VARCHAR(45) NOT NULL,
                        os_type VARCHAR(50) NOT NULL,
                        last_seen TIMESTAMP NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        cpu_cores INTEGER DEFAULT 1,
                        ram_total_gb DOUBLE PRECISION DEFAULT 0,
                        disk_total_gb DOUBLE PRECISION DEFAULT 0,
                        tags TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(hostname, ip_address)
                    );

                    CREATE TABLE IF NOT EXISTS jobs (
                        id SERIAL PRIMARY KEY,
                        machine_id INTEGER REFERENCES machines(id) ON DELETE CASCADE,
                        command TEXT NOT NULL,
                        arguments TEXT DEFAULT '[]',
                        script TEXT DEFAULT '',
                        job_type VARCHAR(30) DEFAULT 'shell',
                        priority INTEGER DEFAULT 0,
                        status VARCHAR(20) DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        started_at TIMESTAMP NULL,
                        completed_at TIMESTAMP NULL,
                        stdout TEXT DEFAULT '',
                        stderr TEXT DEFAULT '',
                        return_code INTEGER DEFAULT 0,
                        created_by VARCHAR(100) DEFAULT 'admin'
                    );

                    CREATE TABLE IF NOT EXISTS metrics (
                        id SERIAL PRIMARY KEY,
                        machine_id INTEGER REFERENCES machines(id) ON DELETE CASCADE,
                        cpu_percent DOUBLE PRECISION,
                        memory_percent DOUBLE PRECISION,
                        disk_percent DOUBLE PRECISION,
                        network_rx_sec DOUBLE PRECISION DEFAULT 0,
                        network_tx_sec DOUBLE PRECISION DEFAULT 0,
                        load_avg DOUBLE PRECISION DEFAULT 0,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS file_transfers (
                        id SERIAL PRIMARY KEY,
                        source_machine_id INTEGER,
                        destination_machine_id INTEGER,
                        filename VARCHAR(255) NOT NULL,
                        file_path TEXT DEFAULT '',
                        size_bytes BIGINT DEFAULT 0,
                        checksum VARCHAR(64) DEFAULT '',
                        status VARCHAR(20) DEFAULT 'pending',
                        error_message TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP NULL
                    );

                    CREATE TABLE IF NOT EXISTS alerts (
                        id SERIAL PRIMARY KEY,
                        machine_id INTEGER REFERENCES machines(id) ON DELETE CASCADE,
                        alert_type VARCHAR(50) NOT NULL,
                        severity VARCHAR(20) NOT NULL,
                        message TEXT NOT NULL,
                        value DOUBLE PRECISION DEFAULT 0,
                        is_resolved BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        resolved_at TIMESTAMP NULL
                    );

                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(100) UNIQUE NOT NULL,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        hashed_password VARCHAR(255) NOT NULL,
                        role VARCHAR(50) DEFAULT 'admin',
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_login TIMESTAMP NULL
                    );

                    CREATE TABLE IF NOT EXISTS system_logs (
                        id SERIAL PRIMARY KEY,
                        machine_id INTEGER NULL,
                        level VARCHAR(20) DEFAULT 'INFO',
                        source VARCHAR(100) DEFAULT 'system',
                        message TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_machines_last_seen ON machines(last_seen);
                    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                    CREATE INDEX IF NOT EXISTS idx_metrics_machine_time ON metrics(machine_id, timestamp);
                    CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(is_resolved);
                    CREATE INDEX IF NOT EXISTS idx_logs_time ON system_logs(timestamp);
                ''')
        logger.info("Tables NebulaLab vérifiées / créées avec succès")

    # ==================== MACHINES ====================
    async def create_or_update_machine(self, m: dict) -> dict:
        """Enregistre ou met à jour une machine (Pop!_OS, Ubuntu, Android, etc.)"""
        last_seen = m.get('last_seen', datetime.now(timezone.utc))
        if isinstance(last_seen, str):
            try:
                last_seen = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
            except Exception:
                last_seen = datetime.now(timezone.utc)

        existing = await self._fetchrow(
            "SELECT id FROM machines WHERE hostname = $1 AND ip_address = $2",
            m['hostname'], m['ip_address']
        )
        if existing:
            await self._execute(
                '''UPDATE machines SET os_type = $1, last_seen = $2, is_active = $3,
                   cpu_cores = $4, ram_total_gb = $5, disk_total_gb = $6, tags = $7, updated_at = $8
                   WHERE id = $9''',
                m.get('os_type', 'linux'), last_seen, True,
                m.get('cpu_cores', 1), m.get('ram_total_gb', 0.0), m.get('disk_total_gb', 0.0),
                m.get('tags', ''), datetime.now(timezone.utc), existing['id']
            )
            return await self.get_machine(existing['id'])
        else:
            if self.is_sqlite:
                import aiosqlite
                async with aiosqlite.connect(self.sqlite_db_path) as conn:
                    cursor = await conn.execute(
                        '''INSERT INTO machines (hostname, ip_address, os_type, last_seen, is_active, cpu_cores, ram_total_gb, disk_total_gb, tags)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (m['hostname'], m['ip_address'], m.get('os_type', 'linux'),
                         self._serialize_sqlite_arg(last_seen), 1,
                         m.get('cpu_cores', 1), m.get('ram_total_gb', 0.0), m.get('disk_total_gb', 0.0), m.get('tags', ''))
                    )
                    await conn.commit()
                    machine_id = cursor.lastrowid
                    return await self.get_machine(machine_id)
            else:
                row = await self._fetchrow(
                    '''INSERT INTO machines (hostname, ip_address, os_type, last_seen, is_active, cpu_cores, ram_total_gb, disk_total_gb, tags)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                       RETURNING *''',
                    m['hostname'], m['ip_address'], m.get('os_type', 'linux'),
                    last_seen, True,
                    m.get('cpu_cores', 1), m.get('ram_total_gb', 0.0), m.get('disk_total_gb', 0.0), m.get('tags', '')
                )
                return row

    async def get_machine(self, machine_id: int) -> Optional[dict]:
        return await self._fetchrow("SELECT * FROM machines WHERE id = $1", machine_id)

    async def get_machine_by_hostname(self, hostname: str) -> Optional[dict]:
        return await self._fetchrow("SELECT * FROM machines WHERE hostname = $1", hostname)

    async def get_all_machines(self) -> List[dict]:
        return await self._fetchall("SELECT * FROM machines ORDER BY last_seen DESC")

    async def update_machine_heartbeat(self, machine_id: int):
        await self._execute(
            "UPDATE machines SET last_seen = $1, is_active = $2 WHERE id = $3",
            datetime.now(timezone.utc), True, machine_id
        )

    async def delete_machine(self, machine_id: int):
        await self._execute("DELETE FROM machines WHERE id = $1", machine_id)

    # ==================== TAGS ====================
    async def get_all_tags(self) -> List[str]:
        """Récupère tous les tags uniques utilisés dans le cluster"""
        machines = await self.get_all_machines()
        tags_set = set()
        for m in machines:
            tags_str = m.get('tags', '')
            if tags_str:
                for tag in tags_str.split(','):
                    tag = tag.strip()
                    if tag:
                        tags_set.add(tag)
        return sorted(list(tags_set))

    async def add_tag_to_machine(self, machine_id: int, tag: str) -> bool:
        """Ajoute un tag à une machine spécifique"""
        machine = await self.get_machine(machine_id)
        if not machine:
            return False

        current_tags = machine.get('tags', '')
        tag_list = [t.strip() for t in current_tags.split(',') if t.strip()] if current_tags else []

        if tag not in tag_list:
            tag_list.append(tag)
            new_tags = ','.join(tag_list)
            await self._execute(
                "UPDATE machines SET tags = $1 WHERE id = $2",
                new_tags, machine_id
            )
            return True
        return False

    async def remove_tag_from_machine(self, machine_id: int, tag: str) -> bool:
        """Retire un tag d'une machine spécifique"""
        machine = await self.get_machine(machine_id)
        if not machine:
            return False

        current_tags = machine.get('tags', '')
        tag_list = [t.strip() for t in current_tags.split(',') if t.strip()] if current_tags else []

        if tag in tag_list:
            tag_list.remove(tag)
            new_tags = ','.join(tag_list)
            await self._execute(
                "UPDATE machines SET tags = $1 WHERE id = $2",
                new_tags, machine_id
            )
            return True
        return False

    async def get_machine_tags(self, machine_id: int) -> List[str]:
        """Récupère la liste des tags d'une machine sous forme de liste de chaînes"""
        machine = await self.get_machine(machine_id)
        if not machine:
            return []
        current_tags = machine.get('tags', '')
        return [t.strip() for t in current_tags.split(',') if t.strip()] if current_tags else []

    async def get_machines_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Récupère toutes les machines actives possédant un tag spécifique"""
        machines = await self.get_all_machines()
        result = []
        for m in machines:
            if not m.get('is_active'):
                continue
            tags_str = m.get('tags', '')
            if tags_str:
                tag_list = [t.strip() for t in tags_str.split(',') if t.strip()]
                if tag in tag_list:
                    result.append(m)
        return result

    async def get_machines_by_tags(self, tags: List[str]) -> List[Dict[str, Any]]:
        """Récupère toutes les machines actives possédant tous les tags spécifiés"""
        if not tags:
            return await self.get_all_machines()  # Return all if no tags specified? Or empty? Let's return all active for safety.
        machines = await self.get_all_machines()
        result = []
        for m in machines:
            if not m.get('is_active'):
                continue
            tags_str = m.get('tags', '')
            machine_tags = set([t.strip() for t in tags_str.split(',') if t.strip()]) if tags_str else set()
            # Check if all required tags are present
            if all(t in machine_tags for t in tags):
                result.append(m)
        return result

    # ==================== JOBS ====================
    async def create_job(self, job_data: dict) -> dict:
        """Crée un job pour une machine cible"""
        args_json = json.dumps(job_data.get('arguments', [])) if isinstance(job_data.get('arguments'), list) else str(job_data.get('arguments', '[]'))
        
        if self.is_sqlite:
            import aiosqlite
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                cursor = await conn.execute(
                    '''INSERT INTO jobs (machine_id, command, arguments, script, job_type, priority, status, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)''',
                    (job_data['machine_id'], job_data['command'], args_json,
                     job_data.get('script', ''), job_data.get('job_type', 'shell'),
                     job_data.get('priority', 0), job_data.get('created_by', 'admin'))
                )
                await conn.commit()
                return await self.get_job(cursor.lastrowid)
        else:
            return await self._fetchrow(
                '''INSERT INTO jobs (machine_id, command, arguments, script, job_type, priority, status, created_by)
                   VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
                   RETURNING *''',
                job_data['machine_id'], job_data['command'], args_json,
                job_data.get('script', ''), job_data.get('job_type', 'shell'),
                job_data.get('priority', 0), job_data.get('created_by', 'admin')
            )

    async def get_job(self, job_id: int) -> Optional[dict]:
        row = await self._fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        if row and isinstance(row.get('arguments'), str):
            try:
                row['arguments'] = json.loads(row['arguments'])
            except Exception:
                pass
        return row

    async def get_jobs(self, skip: int = 0, limit: int = 100, machine_id: Optional[int] = None) -> List[dict]:
        if machine_id:
            rows = await self._fetchall(
                "SELECT * FROM jobs WHERE machine_id = $1 ORDER BY id DESC LIMIT $2 OFFSET $3",
                machine_id, limit, skip
            )
        else:
            rows = await self._fetchall(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT $1 OFFSET $2",
                limit, skip
            )
        for r in rows:
            if isinstance(r.get('arguments'), str):
                try:
                    r['arguments'] = json.loads(r['arguments'])
                except Exception:
                    pass
        return rows

    async def get_pending_jobs_for_machine(self, machine_id: int) -> List[dict]:
        """Récupère les jobs en attente pour un agent spécifique"""
        rows = await self._fetchall(
            "SELECT * FROM jobs WHERE machine_id = $1 AND status = 'pending' ORDER BY priority DESC, id ASC",
            machine_id
        )
        for r in rows:
            if isinstance(r.get('arguments'), str):
                try:
                    r['arguments'] = json.loads(r['arguments'])
                except Exception:
                    pass
        return rows

    async def update_job_status(self, job_id: int, status: str, stdout: str = "", stderr: str = "", return_code: int = 0):
        now = datetime.now(timezone.utc)
        if status == 'running':
            await self._execute(
                "UPDATE jobs SET status = $1, started_at = $2 WHERE id = $3",
                status, now, job_id
            )
        elif status in ['completed', 'failed', 'cancelled']:
            await self._execute(
                '''UPDATE jobs SET status = $1, completed_at = $2, stdout = $3, stderr = $4, return_code = $5
                   WHERE id = $6''',
                status, now, stdout, stderr, return_code, job_id
            )
        else:
            await self._execute("UPDATE jobs SET status = $1 WHERE id = $2", status, job_id)

    # ==================== METRICS ====================
    async def create_metrics(self, m: dict) -> dict:
        ts = m.get('timestamp', datetime.now(timezone.utc))
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except Exception:
                ts = datetime.now(timezone.utc)

        if self.is_sqlite:
            import aiosqlite
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                cursor = await conn.execute(
                    '''INSERT INTO metrics (machine_id, cpu_percent, memory_percent, disk_percent, network_rx_sec, network_tx_sec, load_avg, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (m['machine_id'], m['cpu_percent'], m['memory_percent'], m['disk_percent'],
                     m.get('network_rx_sec', 0.0), m.get('network_tx_sec', 0.0), m.get('load_avg', 0.0),
                     self._serialize_sqlite_arg(ts))
                )
                await conn.commit()
                return {"id": cursor.lastrowid, **m}
        else:
            return await self._fetchrow(
                '''INSERT INTO metrics (machine_id, cpu_percent, memory_percent, disk_percent, network_rx_sec, network_tx_sec, load_avg, timestamp)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   RETURNING *''',
                m['machine_id'], m['cpu_percent'], m['memory_percent'], m['disk_percent'],
                m.get('network_rx_sec', 0.0), m.get('network_tx_sec', 0.0), m.get('load_avg', 0.0), ts
            )

    async def get_machine_metrics(self, machine_id: int, limit: int = 60) -> List[dict]:
        return await self._fetchall(
            "SELECT * FROM metrics WHERE machine_id = $1 ORDER BY timestamp DESC LIMIT $2",
            machine_id, limit
        )

    async def get_latest_metrics_for_all(self) -> List[dict]:
        """Dernière métrique pour chaque machine"""
        machines = await self.get_all_machines()
        latest = []
        for m in machines:
            row = await self._fetchrow(
                "SELECT * FROM metrics WHERE machine_id = $1 ORDER BY timestamp DESC LIMIT 1",
                m['id']
            )
            if row:
                latest.append(row)
        return latest

    # ==================== ALERTS ====================
    async def create_alert(self, a: dict) -> dict:
        if self.is_sqlite:
            import aiosqlite
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                cursor = await conn.execute(
                    '''INSERT INTO alerts (machine_id, alert_type, severity, message, value, is_resolved)
                       VALUES (?, ?, ?, ?, ?, 0)''',
                    (a['machine_id'], a['alert_type'], a['severity'], a['message'], a.get('value', 0.0))
                )
                await conn.commit()
                return {"id": cursor.lastrowid, **a, "is_resolved": False}
        else:
            return await self._fetchrow(
                '''INSERT INTO alerts (machine_id, alert_type, severity, message, value, is_resolved)
                   VALUES ($1, $2, $3, $4, $5, FALSE)
                   RETURNING *''',
                a['machine_id'], a['alert_type'], a['severity'], a['message'], a.get('value', 0.0)
            )

    async def get_unresolved_alerts(self) -> List[dict]:
        return await self._fetchall(
            "SELECT a.*, m.hostname FROM alerts a LEFT JOIN machines m ON a.machine_id = m.id WHERE a.is_resolved = $1 ORDER BY a.created_at DESC",
            0 if self.is_sqlite else False
        )

    async def get_resolved_alerts(self, limit: int = 50) -> List[dict]:
        return await self._fetchall(
            "SELECT a.*, m.hostname FROM alerts a LEFT JOIN machines m ON a.machine_id = m.id WHERE a.is_resolved = $1 ORDER BY a.resolved_at DESC LIMIT $2",
            1 if self.is_sqlite else True, limit
        )

    async def resolve_alert(self, alert_id: int):
        await self._execute(
            "UPDATE alerts SET is_resolved = $1, resolved_at = $2 WHERE id = $3",
            1 if self.is_sqlite else True, datetime.now(timezone.utc), alert_id
        )

    async def resolve_all_alerts(self):
        await self._execute(
            "UPDATE alerts SET is_resolved = $1, resolved_at = $2 WHERE is_resolved = $3",
            1 if self.is_sqlite else True, datetime.now(timezone.utc), 0 if self.is_sqlite else False
        )

    # ==================== USERS & AUTH ====================
    async def get_user_by_username(self, username: str) -> Optional[dict]:
        return await self._fetchrow("SELECT * FROM users WHERE username = $1", username)

    async def get_user_by_id(self, user_id: int) -> Optional[dict]:
        return await self._fetchrow("SELECT * FROM users WHERE id = $1", user_id)

    async def create_user(self, username: str, email: str, hashed_password: str, role: str = 'admin') -> int:
        if self.is_sqlite:
            import aiosqlite
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                cursor = await conn.execute(
                    '''INSERT INTO users (username, email, hashed_password, role, is_active)
                       VALUES (?, ?, ?, ?, 1)''',
                    (username, email, hashed_password, role)
                )
                await conn.commit()
                return cursor.lastrowid
        else:
            row = await self._fetchrow(
                '''INSERT INTO users (username, email, hashed_password, role, is_active)
                   VALUES ($1, $2, $3, $4, TRUE)
                   RETURNING id''',
                username, email, hashed_password, role
            )
            return row['id'] if row else 0

    async def update_last_login(self, user_id: int):
        await self._execute(
            "UPDATE users SET last_login = $1 WHERE id = $2",
            datetime.now(timezone.utc), user_id
        )

    async def list_users(self) -> List[dict]:
        return await self._fetchall("SELECT id, username, email, role, is_active, created_at, last_login FROM users")

    # ==================== LOGS CENTRALISÉS ====================
    async def create_log(self, machine_id: Optional[int], level: str, source: str, message: str) -> dict:
        ts = datetime.now(timezone.utc)
        if self.is_sqlite:
            import aiosqlite
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                cursor = await conn.execute(
                    '''INSERT INTO system_logs (machine_id, level, source, message, timestamp)
                       VALUES (?, ?, ?, ?, ?)''',
                    (machine_id, level.upper(), source, message, self._serialize_sqlite_arg(ts))
                )
                await conn.commit()
                return {"id": cursor.lastrowid, "machine_id": machine_id, "level": level, "source": source, "message": message, "timestamp": ts.isoformat()}
        else:
            return await self._fetchrow(
                '''INSERT INTO system_logs (machine_id, level, source, message, timestamp)
                   VALUES ($1, $2, $3, $4, $5)
                   RETURNING *''',
                machine_id, level.upper(), source, message, ts
            )

    async def get_logs(self, limit: int = 100, level: Optional[str] = None, machine_id: Optional[int] = None) -> List[dict]:
        query = "SELECT l.*, m.hostname FROM system_logs l LEFT JOIN machines m ON l.machine_id = m.id WHERE 1=1"
        params = []
        if level:
            params.append(level.upper())
            query += f" AND l.level = ${len(params)}"
        if machine_id:
            params.append(machine_id)
            query += f" AND l.machine_id = ${len(params)}"
        params.append(limit)
        query += f" ORDER BY l.id DESC LIMIT ${len(params)}"
        return await self._fetchall(query, *params)

    # ==================== FILE TRANSFERS ====================
    async def create_file_transfer(self, transfer_data: dict) -> dict:
        if self.is_sqlite:
            import aiosqlite
            async with aiosqlite.connect(self.sqlite_db_path) as conn:
                cursor = await conn.execute(
                    '''INSERT INTO file_transfers (source_machine_id, destination_machine_id, filename, file_path, size_bytes, checksum, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'in_progress')''',
                    (transfer_data.get('source_machine_id'), transfer_data.get('destination_machine_id'),
                     transfer_data['filename'], transfer_data.get('file_path', ''),
                     transfer_data.get('size_bytes', 0), transfer_data.get('checksum', ''))
                )
                await conn.commit()
                return {"id": cursor.lastrowid, **transfer_data, "status": "in_progress"}
        else:
            return await self._fetchrow(
                '''INSERT INTO file_transfers (source_machine_id, destination_machine_id, filename, file_path, size_bytes, checksum, status)
                   VALUES ($1, $2, $3, $4, $5, $6, 'in_progress')
                   RETURNING *''',
                transfer_data.get('source_machine_id'), transfer_data.get('destination_machine_id'),
                transfer_data['filename'], transfer_data.get('file_path', ''),
                transfer_data.get('size_bytes', 0), transfer_data.get('checksum', '')
            )

    async def update_file_transfer(self, transfer_id: int, status: str, error_message: str = ""):
        await self._execute(
            '''UPDATE file_transfers SET status = $1, error_message = $2, completed_at = $3
               WHERE id = $4''',
            status, error_message, datetime.now(timezone.utc), transfer_id
        )

    async def get_file_transfers(self, limit: int = 50) -> List[dict]:
        return await self._fetchall(
            '''SELECT t.*, s.hostname as source_hostname, d.hostname as destination_hostname
               FROM file_transfers t
               LEFT JOIN machines s ON t.source_machine_id = s.id
               LEFT JOIN machines d ON t.destination_machine_id = d.id
               ORDER BY t.id DESC LIMIT $1''',
            limit
        )