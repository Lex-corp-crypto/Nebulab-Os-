"""
Main API Service for NebulaLab (Distributed Linux Lab)
Fournit des endpoints REST complets et sécurisés pour l'orchestration du cluster,
le monitoring en temps réel, l'exécution des jobs, le partage de fichiers, les alertes et les logs.
Expose également un endpoint Prometheus et un flux WebSocket bidirectionnel.
"""

import os
import io
import json
import socket
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
import psutil

from fastapi import FastAPI, HTTPException, Depends, status, Request, UploadFile, File, Form, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, JSONResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry, REGISTRY

# Modules locaux
from database import DatabaseManager
from auth_manager import AuthManager
from job_manager import JobManager
from websocket_manager import WebSocketManager
from alerting_system import AlertingSystem
from file_transfer import FileTransferManager
from service_discovery import ServiceDiscovery
from tunnel_manager import tunnel_instance

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("nebulalab.api")

SECRET_KEY = os.getenv("SECRET_KEY", "nebulalab-super-secret-cluster-key-2026")

# Prometheus Metrics (using default registry safely)
try:
    REQUEST_COUNT = Counter('nebulalab_http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
    REQUEST_LATENCY = Histogram('nebulalab_http_request_duration_seconds', 'HTTP request latency', ['method', 'endpoint'])
    ACTIVE_NODES_GAUGE = Gauge('nebulalab_active_nodes', 'Number of active cluster nodes')
    JOBS_TOTAL = Counter('nebulalab_jobs_total', 'Total jobs processed', ['status'])
    ALERTS_ACTIVE_GAUGE = Gauge('nebulalab_active_alerts', 'Number of currently active alerts')
except ValueError:
    # Déjà enregistré en cas de reload
    REQUEST_COUNT = REGISTRY._names_to_collectors.get('nebulalab_http_requests_total')
    REQUEST_LATENCY = REGISTRY._names_to_collectors.get('nebulalab_http_request_duration_seconds')
    ACTIVE_NODES_GAUGE = REGISTRY._names_to_collectors.get('nebulalab_active_nodes')
    JOBS_TOTAL = REGISTRY._names_to_collectors.get('nebulalab_jobs_total')
    ALERTS_ACTIVE_GAUGE = REGISTRY._names_to_collectors.get('nebulalab_active_alerts')

# Initialisation des sous-systèmes
db_manager = DatabaseManager()
auth_manager = AuthManager(db_manager, SECRET_KEY)
job_manager = JobManager(db_manager)
websocket_manager = WebSocketManager()
alerting_system = AlertingSystem(db_manager, websocket_manager)
file_transfer_manager = FileTransferManager()
discovery_service = ServiceDiscovery(role="master", service_port=8000)

async def background_cluster_monitor():
    """Vérification périodique de l'état des nœuds et des alertes"""
    while True:
        try:
            await alerting_system.check_offline_nodes()
            # Mettre à jour les jauges Prometheus
            machines = await db_manager.get_all_machines()
            active_count = len([m for m in machines if m.get("is_active")])
            if ACTIVE_NODES_GAUGE:
                ACTIVE_NODES_GAUGE.set(active_count)
            
            alerts = await db_manager.get_unresolved_alerts()
            if ALERTS_ACTIVE_GAUGE:
                ALERTS_ACTIVE_GAUGE.set(len(alerts))
        except Exception as e:
            logger.debug(f"Moniteur de cluster : {e}")
        await asyncio.sleep(10)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Démarrage du Core API NebulaLab...")
    await db_manager.connect()
    await auth_manager.ensure_default_admin()
    await discovery_service.initialize()
    
    monitor_task = asyncio.create_task(background_cluster_monitor())
    udp_task = asyncio.create_task(discovery_service.run_udp_broadcast_responder())
    
    tunnel_enabled = os.getenv("TUNNEL_ENABLED", "true").lower() in ["true", "1", "yes"]
    tunnel_task = None
    if tunnel_enabled:
        tunnel_task = asyncio.create_task(tunnel_instance.start_async_supervisor())
        
    logger.info("✅ NebulaLab Core API opérationnel sur http://0.0.0.0:8000")
    
    yield
    
    if tunnel_task:
        tunnel_task.cancel()
    tunnel_instance.stop()
    monitor_task.cancel()
    udp_task.cancel()
    discovery_service.stop()
    await db_manager.disconnect()
    logger.info("NebulaLab Core API arrêté")

app = FastAPI(
    title="NebulaLab OS API",
    description="Distributed Linux Lab - Cluster Orchestration, Monitoring & Jobs API",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

# ==================== PYDANTIC SCHEMAS ====================
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: Optional[str] = "admin"

class MachineRegisterPayload(BaseModel):
    hostname: str
    ip_address: str
    os_type: str = "linux"
    cpu_cores: Optional[int] = 1
    ram_total_gb: Optional[float] = 0.0
    disk_total_gb: Optional[float] = 0.0
    tags: Optional[str] = ""

class JobCreateRequest(BaseModel):
    machine_id: Optional[int] = None
    target: Optional[str] = "specific"
    command: str
    arguments: Optional[List[str]] = []
    script: Optional[str] = ""
    job_type: Optional[str] = "shell"
    priority: Optional[int] = 0
    tag: Optional[str] = None
    tags: Optional[Any] = None

class JobStatusUpdateRequest(BaseModel):
    status: str
    stdout: Optional[str] = ""
    stderr: Optional[str] = ""
    return_code: Optional[int] = 0

class MetricsSubmitPayload(BaseModel):
    machine_id: int
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_rx_sec: Optional[float] = 0.0
    network_tx_sec: Optional[float] = 0.0
    load_avg: Optional[float] = 0.0
    timestamp: Optional[str] = None

class LogSubmitPayload(BaseModel):
    machine_id: Optional[int] = None
    level: str = "INFO"
    source: str = "agent"
    message: str

class TunnelConfigPayload(BaseModel):
    provider: Optional[str] = "auto"
    ngrok_authtoken: Optional[str] = ""


# ==================== AUTH DEPENDENCY ====================
async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton d'authentification manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = auth_manager.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Jeton invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = payload.get("sub")
    user = await auth_manager.db_manager.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    return user


async def get_optional_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    if not credentials:
        return None
    token = credentials.credentials
    payload = auth_manager.verify_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    return await auth_manager.db_manager.get_user_by_username(username)


# ==================== MIDDLEWARE METRICS ====================
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = datetime.now(timezone.utc)
    response = await call_next(request)
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    
    endpoint = request.url.path
    if not endpoint.startswith("/static") and REQUEST_COUNT:
        REQUEST_COUNT.labels(method=request.method, endpoint=endpoint, status=response.status_code).inc()
        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(duration)
    return response


# ==================== HEALTH & PROMETHEUS ====================
@app.get("/health")
@app.head("/health")
async def health_check():
    return {
        "status": "healthy",
        "system": "NebulaLab OS",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/metrics")
async def prometheus_metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ==================== AUTH ENDPOINTS ====================
@app.post("/api/auth/login")
@app.post("/token")
async def login(req: LoginRequest):
    user = await auth_manager.authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_manager.create_access_token(data={"sub": user["username"], "role": user.get("role", "admin")})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user.get("role", "admin")
        }
    }

@app.post("/api/auth/register")
async def register_user(req: RegisterUserRequest, current_user: dict = Depends(get_current_user)):
    existing = await db_manager.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=400, detail="Nom d'utilisateur déjà utilisé")
    user = await auth_manager.create_user(req.username, req.email, req.password, req.role or "admin")
    return {"message": "Utilisateur créé", "user": user}

@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "email": current_user["email"],
        "role": current_user.get("role", "admin")
    }


# ==================== CLUSTER OVERVIEW ====================
def get_server_network_ips() -> List[str]:
    ips = []
    if discovery_service and discovery_service.ip_address and discovery_service.ip_address != "127.0.0.1":
        ips.append(discovery_service.ip_address)
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    if addr.address not in ips:
                        ips.append(addr.address)
    except Exception:
        pass
    if not ips:
        ips.append("127.0.0.1")
    return ips

@app.get("/api/overview")
async def get_cluster_overview():
    """Fournit un résumé complet du cluster pour le dashboard et le mobile"""
    machines = await db_manager.get_all_machines()
    latest_metrics = await db_manager.get_latest_metrics_for_all()
    active_alerts = await db_manager.get_unresolved_alerts()
    job_stats = await job_manager.get_statistics()
    
    metrics_map = {m["machine_id"]: m for m in latest_metrics}
    
    nodes = []
    total_cpu_load = 0.0
    total_ram_load = 0.0
    total_disk_load = 0.0
    
    for m in machines:
        mid = m["id"]
        metric = metrics_map.get(mid, {
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "disk_percent": 0.0,
            "network_rx_sec": 0.0,
            "network_tx_sec": 0.0,
            "load_avg": 0.0
        })
        node_info = dict(m)
        node_info["metrics"] = metric
        nodes.append(node_info)
        
        if m.get("is_active"):
            total_cpu_load += metric.get("cpu_percent", 0.0)
            total_ram_load += metric.get("memory_percent", 0.0)
            total_disk_load += metric.get("disk_percent", 0.0)

    active_count = len([m for m in machines if m.get("is_active")])
    avg_cpu = round(total_cpu_load / max(1, active_count), 1)
    avg_ram = round(total_ram_load / max(1, active_count), 1)
    avg_disk = round(total_disk_load / max(1, active_count), 1)

    server_ips = get_server_network_ips()
    master_ip = server_ips[0] if server_ips else "127.0.0.1"
    tunnel_status = tunnel_instance.get_status()
    public_url = tunnel_status.get("public_url")

    return {
        "cluster_name": "NebulaLab Cloud",
        "master_ip": master_ip,
        "available_ips": server_ips,
        "public_url": public_url,
        "tunnel": tunnel_status,
        "total_nodes": len(machines),
        "active_nodes": active_count,
        "cluster_averages": {
            "cpu_percent": avg_cpu,
            "memory_percent": avg_ram,
            "disk_percent": avg_disk
        },
        "active_alerts_count": len(active_alerts),
        "job_stats": job_stats,
        "nodes": nodes,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/system/network")
async def get_network_info():
    ips = get_server_network_ips()
    tunnel_status = tunnel_instance.get_status()
    return {
        "master_ip": ips[0] if ips else "127.0.0.1",
        "available_ips": ips,
        "public_url": tunnel_status.get("public_url"),
        "tunnel": tunnel_status,
        "port": 8000
    }

def get_effective_base_url(request: Request) -> str:
    """Détermine l'URL publique ou locale accessible du Master pour les nœuds clients"""
    tunnel_url = tunnel_instance.get_saved_url()
    if tunnel_url and tunnel_url.startswith("http"):
        return tunnel_url.rstrip("/")
    
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    if host and "127.0.0.1" not in host and "localhost" not in host:
        return f"{proto}://{host}".rstrip("/")
    
    server_ips = get_server_network_ips()
    ip = server_ips[0] if server_ips else "localhost"
    return f"http://{ip}:8000"

@app.get("/join", response_class=PlainTextResponse)
@app.get("/install", response_class=PlainTextResponse)
async def generate_linux_agent_installer(request: Request):
    """Génère un script d'installation 1-ligne pré-configuré sans saisie manuelle d'IP"""
    master_url = get_effective_base_url(request)
    return f"""#!/usr/bin/env bash
# ==============================================================================
# NebulaLab OS - 1-Line Zero-Config Agent Installer
# Connecte automatiquement ce nœud au Master NebulaLab sans saisir d'IP ni de port
# ==============================================================================
set -e

MASTER_URL="${{1:-{master_url}}}"

echo "=================================================================="
echo "  🌌 Connexion du Nœud au Master NebulaLab OS"
echo "  🌐 URL Master : $MASTER_URL"
echo "=================================================================="

if [ -n "$ANDROID_ROOT" ] || [ -d "/data/data/com.termux" ]; then
    echo "📱 Détection : Android (Termux)"
    pkg update -y 2>/dev/null || true
    pkg install -y python python-pip git curl 2>/dev/null || true
else
    echo "💻 Détection : Linux Standard"
    if command -v apt-get >/dev/null 2>&1; then
        (sudo apt-get update -y && sudo apt-get install -y python3 python3-pip python3-venv curl) 2>/dev/null || true
    elif command -v dnf >/dev/null 2>&1; then
        (sudo dnf install -y python3 python3-pip curl) 2>/dev/null || true
    elif command -v pacman >/dev/null 2>&1; then
        (sudo pacman -Sy --noconfirm python python-pip curl) 2>/dev/null || true
    fi
fi

INSTALL_DIR="$HOME/.nebulalab_agent"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    echo "📦 Initialisation de l'environnement virtuel Python..."
    python3 -m venv "$INSTALL_DIR/.venv" 2>/dev/null || python -m venv "$INSTALL_DIR/.venv" 2>/dev/null || true
fi

PYTHON_BIN="$INSTALL_DIR/.venv/bin/python"
PIP_BIN="$INSTALL_DIR/.venv/bin/pip"

if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
    PIP_BIN="pip3"
fi

echo "📥 Installation des dépendances agent (psutil, aiohttp, zeroconf)..."
"$PIP_BIN" install --upgrade pip >/dev/null 2>&1 || true
"$PIP_BIN" install psutil aiohttp zeroconf cryptography requests >/dev/null 2>&1 || true

echo "📥 Téléchargement des modules depuis $MASTER_URL..."
curl -sSL -k "$MASTER_URL/static/agent_service.py" -o "$INSTALL_DIR/agent_service.py"
curl -sSL -k "$MASTER_URL/static/service_discovery.py" -o "$INSTALL_DIR/service_discovery.py"
curl -sSL -k "$MASTER_URL/static/file_transfer.py" -o "$INSTALL_DIR/file_transfer.py"

echo "🚀 Lancement de l'agent NebulaLab..."
echo "  Hôte : $(hostname)"
echo "  Cible: $MASTER_URL"
echo "=================================================================="

export API_URL="$MASTER_URL"
export HOSTNAME="$(hostname)"

exec "$PYTHON_BIN" "$INSTALL_DIR/agent_service.py"
"""

@app.get("/join.ps1", response_class=PlainTextResponse)
@app.get("/install.ps1", response_class=PlainTextResponse)
async def generate_windows_agent_installer(request: Request):
    """Génère un script PowerShell 1-ligne pré-configuré pour nœuds Windows"""
    master_url = get_effective_base_url(request)
    return f"""# ==============================================================================
# NebulaLab OS - 1-Line Windows PowerShell Agent Installer
# ==============================================================================
$ErrorActionPreference = "Stop"
$MasterUrl = "{master_url}"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  🌌 Connexion du Nœud Windows à NebulaLab OS" -ForegroundColor Cyan
Write-Host "  🌐 URL Master : $MasterUrl" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

$InstallDir = "$env:USERPROFILE\\.nebulalab_agent"
if (-not (Test-Path $InstallDir)) {{
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}}
Set-Location $InstallDir

Write-Host "📥 Installation des dépendances Python..." -ForegroundColor Yellow
pip install --upgrade pip psutil aiohttp zeroconf cryptography requests

Write-Host "📥 Téléchargement des modules depuis $MasterUrl..." -ForegroundColor Yellow
Invoke-WebRequest -Uri "$MasterUrl/static/agent_service.py" -OutFile "$InstallDir\\agent_service.py"
Invoke-WebRequest -Uri "$MasterUrl/static/service_discovery.py" -OutFile "$InstallDir\\service_discovery.py"
Invoke-WebRequest -Uri "$MasterUrl/static/file_transfer.py" -OutFile "$InstallDir\\file_transfer.py"

Write-Host "🚀 Lancement de l'agent NebulaLab..." -ForegroundColor Green
$env:API_URL = "$MasterUrl"
$env:HOSTNAME = "$env:COMPUTERNAME"

python "$InstallDir\\agent_service.py"
"""

@app.get("/api/tunnel")
async def get_tunnel():
    return tunnel_instance.get_status()

@app.post("/api/tunnel/configure")
async def configure_tunnel(payload: TunnelConfigPayload, current_user: Optional[dict] = Depends(get_optional_current_user)):
    """Configure le provider tunnel et le token ngrok optionnel, puis redémarre le tunnel"""
    tunnel_instance.save_config_to_env(payload.provider, payload.ngrok_authtoken)
    tunnel_instance.stop()
    url = await asyncio.get_running_loop().run_in_executor(None, tunnel_instance.start)
    return {
        "status": "ok",
        "url": url,
        "tunnel": tunnel_instance.get_status()
    }

@app.post("/api/tunnel/restart")
async def restart_tunnel(current_user: Optional[dict] = Depends(get_optional_current_user)):
    tunnel_instance.stop()
    url = await asyncio.get_running_loop().run_in_executor(None, tunnel_instance.start)
    return {"status": "ok", "url": url, "tunnel": tunnel_instance.get_status()}


# ==================== MACHINES & AGENTS ====================
@app.get("/api/machines")
async def list_machines():
    machines = await db_manager.get_all_machines()
    latest_metrics = await db_manager.get_latest_metrics_for_all()
    metrics_map = {m["machine_id"]: m for m in latest_metrics}
    
    result = []
    for m in machines:
        item = dict(m)
        item["metrics"] = metrics_map.get(m["id"])
        result.append(item)
    return result

@app.post("/api/machines/register")
@app.post("/machines")
async def register_machine(payload: MachineRegisterPayload):
    machine = await db_manager.create_or_update_machine(payload.model_dump())
    logger.info(f"Nœud enregistré : {machine['hostname']} ({machine['os_type']}) @ {machine['ip_address']}")
    
    await websocket_manager.broadcast_json({
        "type": "node_registered",
        "machine": machine
    })
    return machine
# ==================== TAGS ====================
@app.get("/api/tags")
async def get_all_tags():
    """Récupère tous les tags uniques utilisés dans le cluster"""
    tags = await db_manager.get_all_tags()
    return {"tags": tags}

@app.post("/api/machines/{machine_id}/tags")
async def add_tag_to_machine(machine_id: int, tag: dict):
    """Ajoute un tag à une machine spécifique"""
    tag_value = tag.get("tag", "").strip()
    if not tag_value:
        raise HTTPException(status_code=400, detail="Tag ne peut pas être vide")

    success = await db_manager.add_tag_to_machine(machine_id, tag_value)
    if not success:
        raise HTTPException(status_code=404, detail="Machine non trouvée")

    # Broadcast the update
    machine = await db_manager.get_machine(machine_id)
    await websocket_manager.broadcast_json({
        "type": "machine_tag_added",
        "machine_id": machine_id,
        "tag": tag_value,
        "machine": machine
    })

    return {"status": "ok", "machine_id": machine_id, "tag": tag_value}

@app.delete("/api/machines/{machine_id}/tags/{tag}")
async def remove_tag_from_machine(machine_id: int, tag: str):
    """Retire un tag d'une machine spécifique"""
    # URL decode the tag if needed
    tag = tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag ne peut pas être vide")

    success = await db_manager.remove_tag_from_machine(machine_id, tag)
    if not success:
        raise HTTPException(status_code=404, detail="Machine non trouvée ou tag absent")

    # Broadcast the update
    machine = await db_manager.get_machine(machine_id)
    await websocket_manager.broadcast_json({
        "type": "machine_tag_removed",
        "machine_id": machine_id,
        "tag": tag,
        "machine": machine
    })

    return {"status": "ok", "machine_id": machine_id, "tag": tag}

@app.get("/api/machines/by-tag/{tag}")
async def get_machines_by_tag(tag: str):
    """Récupère toutes les machines actives possédant un tag spécifique"""
    tag = tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag ne peut pas être vide")

    machines = await db_manager.get_machines_by_tag(tag)
    return {"machines": machines}

@app.get("/api/machines/by-tags")
async def get_machines_by_tags(tags: str):
    """Récupère toutes les machines actives possédant tous les tags spécifiés"""
    # Parse comma-separated tags from query parameter
    tag_list = [t.strip() for t in tags.split(',') if t.strip()] if tags else []
    if not tag_list:
        raise HTTPException(status_code=400, detail="Au moins un tag doit être spécifié")

    machines = await db_manager.get_machines_by_tags(tag_list)
    return {"machines": machines, "tags": tag_list}
@app.get("/api/machines/{machine_id}")
async def get_machine(machine_id: int):
    machine = await db_manager.get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine introuvable")
    return machine

@app.put("/api/machines/{machine_id}/heartbeat")
@app.put("/machines/{machine_id}")
async def heartbeat(machine_id: int):
    await db_manager.update_machine_heartbeat(machine_id)
    return {"status": "ok", "machine_id": machine_id}

@app.delete("/api/machines/{machine_id}")
async def delete_machine(machine_id: int, current_user: Optional[dict] = Depends(get_optional_current_user)):
    await db_manager.delete_machine(machine_id)
    await websocket_manager.broadcast_json({"type": "node_deleted", "machine_id": machine_id})
    return {"message": "Machine supprimée"}


# ==================== METRICS ====================
@app.post("/api/metrics")
@app.post("/metrics_ingest")
async def submit_metrics(payload: MetricsSubmitPayload):
    metric_entry = await db_manager.create_metrics(payload.model_dump())
    
    await alerting_system.check_metrics_and_alert(
        machine_id=payload.machine_id,
        cpu_percent=payload.cpu_percent,
        memory_percent=payload.memory_percent,
        disk_percent=payload.disk_percent
    )
    
    await db_manager.update_machine_heartbeat(payload.machine_id)
    
    await websocket_manager.broadcast_json({
        "type": "metrics_update",
        "machine_id": payload.machine_id,
        "metrics": payload.model_dump()
    })
    return metric_entry

@app.get("/api/metrics/latest")
async def get_latest_metrics():
    return await db_manager.get_latest_metrics_for_all()

@app.get("/api/metrics/{machine_id}")
async def get_machine_metrics(machine_id: int, limit: int = 60):
    return await db_manager.get_machine_metrics(machine_id, limit=limit)


# ==================== JOBS & REMOTE EXECUTION ====================
@app.post("/api/jobs")
async def create_job(req: JobCreateRequest, current_user: Optional[dict] = Depends(get_optional_current_user)):
    user_name = current_user.get("username", "admin") if current_user else "admin"
    job_payload = req.model_dump()
    job_payload["created_by"] = user_name
    
    result = await job_manager.create_job(job_payload)
    
    await websocket_manager.broadcast_json({
        "type": "job_created",
        "job": result
    })
    if JOBS_TOTAL:
        JOBS_TOTAL.labels(status="created").inc()
    return result

@app.get("/api/jobs")
async def list_jobs(skip: int = 0, limit: int = 50, machine_id: Optional[int] = None):
    return await job_manager.get_jobs(skip=skip, limit=limit, machine_id=machine_id)

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: int):
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job

@app.post("/api/jobs/{job_id}/cancel")
@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: int, current_user: Optional[dict] = Depends(get_optional_current_user)):
    success = await job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Impossible d'annuler ce job")
    await websocket_manager.broadcast_json({"type": "job_cancelled", "job_id": job_id})
    return {"message": "Job annulé avec succès"}

# Agent Queue Endpoints
@app.get("/api/agent/{machine_id}/jobs/poll")
async def agent_poll_jobs(machine_id: int):
    pending = await job_manager.get_pending_jobs(machine_id)
    return pending

@app.post("/api/agent/{machine_id}/jobs/{job_id}/status")
async def agent_update_job_status(machine_id: int, job_id: int, payload: JobStatusUpdateRequest):
    await job_manager.update_job_status(
        job_id=job_id,
        status=payload.status,
        stdout=payload.stdout or "",
        stderr=payload.stderr or "",
        return_code=payload.return_code or 0
    )
    await websocket_manager.broadcast_json({
        "type": "job_status_update",
        "job_id": job_id,
        "machine_id": machine_id,
        "status": payload.status,
        "return_code": payload.return_code,
        "stdout": payload.stdout,
        "stderr": payload.stderr
    })
    if JOBS_TOTAL:
        JOBS_TOTAL.labels(status=payload.status).inc()
    return {"status": "recorded"}


# ==================== LOGS CENTRALISÉS ====================
@app.post("/api/logs")
async def submit_log(payload: LogSubmitPayload):
    log_entry = await db_manager.create_log(
        machine_id=payload.machine_id,
        level=payload.level,
        source=payload.source,
        message=payload.message
    )
    await websocket_manager.broadcast_json({
        "type": "log_entry",
        "log": log_entry
    })
    return log_entry

@app.get("/api/logs")
async def get_logs(limit: int = 100, level: Optional[str] = None, machine_id: Optional[int] = None):
    return await db_manager.get_logs(limit=limit, level=level, machine_id=machine_id)


# ==================== ALERTS ====================
@app.get("/api/alerts")
async def get_active_alerts():
    return await alerting_system.get_active_alerts()

@app.get("/api/alerts/history")
async def get_alert_history(limit: int = 50):
    return await db_manager.get_resolved_alerts(limit=limit)

@app.put("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int, current_user: Optional[dict] = Depends(get_optional_current_user)):
    await alerting_system.resolve_alert(alert_id)
    return {"message": f"Alerte #{alert_id} résolue"}

@app.post("/api/alerts/resolve-all")
async def resolve_all_alerts(current_user: Optional[dict] = Depends(get_optional_current_user)):
    await alerting_system.resolve_all_alerts()
    return {"message": "Toutes les alertes ont été marquées comme résolues"}


# ==================== FILE MANAGEMENT & STORAGE ====================
@app.post("/api/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    encrypt: bool = Form(False),
    current_user: Optional[dict] = Depends(get_optional_current_user)
):
    content = await file.read()
    res = await file_transfer_manager.save_uploaded_file(file.filename, content, encrypt=encrypt)
    
    await db_manager.create_file_transfer({
        "source_machine_id": None,
        "destination_machine_id": None,
        "filename": res["filename"],
        "file_path": res["file_path"],
        "size_bytes": res["size_bytes"],
        "checksum": res["checksum"]
    })
    
    await websocket_manager.broadcast_json({
        "type": "file_uploaded",
        "file": res
    })
    return res

@app.get("/api/files")
async def list_files():
    return file_transfer_manager.list_shared_files()

@app.get("/api/files/download/{filename}")
async def download_file(filename: str, decrypt: bool = False):
    safe_path = file_transfer_manager._get_safe_path(filename)
    if not safe_path or not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    
    safe_name = os.path.basename(safe_path)
    if decrypt:
        data = await file_transfer_manager.get_file_content(safe_name, decrypt=True)
        return Response(content=data, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={safe_name}"})
    
    return FileResponse(safe_path, filename=safe_name)

@app.delete("/api/files/{filename}")
async def delete_file(filename: str, current_user: Optional[dict] = Depends(get_optional_current_user)):
    safe_name = os.path.basename(filename)
    success = await file_transfer_manager.delete_file(safe_name)
    if not success:
        raise HTTPException(status_code=404, detail="Fichier introuvable ou impossible à supprimer")

    await websocket_manager.broadcast_json({
        "type": "file_deleted",
        "filename": safe_name
    })
    return {"status": "ok", "message": f"Fichier '{safe_name}' supprimé avec succès"}

@app.get("/api/files/transfers")
async def list_file_transfers():
    return await db_manager.get_file_transfers()


# ==================== WEBSOCKET ENDPOINT ====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket_manager.connect(websocket)
    try:
        overview = await get_cluster_overview()
        await websocket.send_text(json.dumps({
            "type": "cluster_overview",
            "data": overview
        }))
        
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                action = msg.get("action")
                if action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "time": datetime.now(timezone.utc).isoformat()}))
                elif action == "refresh":
                    ov = await get_cluster_overview()
                    await websocket.send_text(json.dumps({"type": "cluster_overview", "data": ov}))
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Déconnexion client WS : {e}")
    finally:
        websocket_manager.disconnect(websocket)


# ==================== DASHBOARD STATIC FILES SERVE ====================
dashboard_public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "dashboard", "public"))
if os.path.exists(dashboard_public_dir):
    app.mount("/static", StaticFiles(directory=dashboard_public_dir), name="static")

    @app.get("/")
    @app.head("/")
    @app.get("/dashboard")
    @app.get("/ui")
    @app.get("/app")
    @app.get("/index.html")
    async def serve_index():
        index_path = os.path.join(dashboard_public_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "NebulaLab API is running."}



if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)