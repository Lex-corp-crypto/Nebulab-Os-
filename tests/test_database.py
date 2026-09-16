"""
Tests for DatabaseManager in NebulaLab OS
"""
import os
import tempfile
import pytest
import pytest_asyncio
from database import DatabaseManager

@pytest_asyncio.fixture
async def temp_db():
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_file.close()
    db = DatabaseManager(f"sqlite:///{temp_file.name}")
    await db.connect()
    yield db
    await db.disconnect()
    if os.path.exists(temp_file.name):
        try:
            os.remove(temp_file.name)
        except Exception:
            pass

@pytest.mark.asyncio
async def test_machine_registration_and_heartbeat(temp_db):
    machine = await temp_db.create_or_update_machine({
        "hostname": "test-node-1",
        "ip_address": "192.168.1.100",
        "os_type": "Ubuntu",
        "cpu_cores": 4,
        "ram_total_gb": 16.0,
        "disk_total_gb": 256.0,
        "tags": "worker,compute"
    })
    assert machine["id"] is not None
    assert machine["hostname"] == "test-node-1"
    assert machine["os_type"] == "Ubuntu"
    assert machine["is_active"] in [1, True]

    # Check retrieve
    fetched = await temp_db.get_machine(machine["id"])
    assert fetched is not None
    assert fetched["hostname"] == "test-node-1"

    # Heartbeat
    await temp_db.update_machine_heartbeat(machine["id"])
    updated = await temp_db.get_machine(machine["id"])
    assert updated["is_active"] in [1, True]

@pytest.mark.asyncio
async def test_tags_management(temp_db):
    machine = await temp_db.create_or_update_machine({
        "hostname": "tag-node",
        "ip_address": "192.168.1.101",
        "os_type": "Pop!_OS",
        "tags": "gpu,ml"
    })
    mid = machine["id"]

    # Add tag
    ok = await temp_db.add_tag_to_machine(mid, "fast")
    assert ok is True
    tags = await temp_db.get_machine_tags(mid)
    assert "gpu" in tags
    assert "ml" in tags
    assert "fast" in tags

    # Filter by tag
    gpu_machines = await temp_db.get_machines_by_tag("gpu")
    assert len(gpu_machines) >= 1
    assert gpu_machines[0]["id"] == mid

    # Filter by multiple tags
    multi = await temp_db.get_machines_by_tags(["gpu", "fast"])
    assert len(multi) >= 1

    # Remove tag
    removed = await temp_db.remove_tag_from_machine(mid, "fast")
    assert removed is True
    tags_after = await temp_db.get_machine_tags(mid)
    assert "fast" not in tags_after

@pytest.mark.asyncio
async def test_jobs_workflow(temp_db):
    machine = await temp_db.create_or_update_machine({
        "hostname": "job-node",
        "ip_address": "192.168.1.102",
        "os_type": "Linux"
    })
    mid = machine["id"]

    # Create job
    job = await temp_db.create_job({
        "machine_id": mid,
        "command": "echo 'test'",
        "arguments": ["hello", "world"],
        "job_type": "shell",
        "priority": 1,
        "created_by": "test-admin"
    })
    assert job["id"] is not None
    assert job["status"] == "pending"

    # Pending jobs for machine
    pending = await temp_db.get_pending_jobs_for_machine(mid)
    assert len(pending) >= 1
    assert pending[0]["id"] == job["id"]

    # Update job status
    await temp_db.update_job_status(job["id"], "completed", stdout="hello world\n", return_code=0)
    finished = await temp_db.get_job(job["id"])
    assert finished["status"] == "completed"
    assert "hello world" in finished["stdout"]
    assert finished["return_code"] == 0

@pytest.mark.asyncio
async def test_metrics_and_alerts(temp_db):
    machine = await temp_db.create_or_update_machine({
        "hostname": "metric-node",
        "ip_address": "192.168.1.103",
        "os_type": "Linux"
    })
    mid = machine["id"]

    # Insert metrics
    metric = await temp_db.create_metrics({
        "machine_id": mid,
        "cpu_percent": 88.5,
        "memory_percent": 65.0,
        "disk_percent": 42.0,
        "network_rx_sec": 12.5,
        "network_tx_sec": 3.4,
        "load_avg": 1.2
    })
    assert metric["id"] is not None

    latest = await temp_db.get_latest_metrics_for_all()
    assert len(latest) >= 1
    assert latest[0]["cpu_percent"] == 88.5

    # Create alert
    alert = await temp_db.create_alert({
        "machine_id": mid,
        "alert_type": "cpu",
        "severity": "warning",
        "message": "High CPU usage",
        "value": 88.5
    })
    assert alert["id"] is not None

    unresolved = await temp_db.get_unresolved_alerts()
    assert len(unresolved) >= 1

    # Resolve alert
    await temp_db.resolve_alert(alert["id"])
    unresolved_after = await temp_db.get_unresolved_alerts()
    assert len([a for a in unresolved_after if a["id"] == alert["id"]]) == 0
