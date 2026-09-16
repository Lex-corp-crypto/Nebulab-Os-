"""
Pydantic Schemas for NebulaLab REST API Endpoints.
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


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


class LoginRequest(BaseModel):
    username: str
    password: str
