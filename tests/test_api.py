"""
Integration tests for NebulaLab FastAPI endpoints
"""
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from main_api import app, db_manager, file_transfer_manager

@pytest.fixture(scope="module")
def client():
    # Configure temporary database for testing
    temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db_file.close()

    temp_storage_dir = tempfile.TemporaryDirectory()
    file_transfer_manager.storage_dir = temp_storage_dir.name

    db_manager.connection_string = f"sqlite:///{temp_db_file.name}"
    db_manager.is_sqlite = True
    db_manager.sqlite_db_path = os.path.abspath(temp_db_file.name)

    # Disable tunnel during test
    os.environ["TUNNEL_ENABLED"] = "false"

    with TestClient(app) as test_client:
        yield test_client

    temp_storage_dir.cleanup()
    if os.path.exists(temp_db_file.name):
        try:
            os.remove(temp_db_file.name)
        except Exception:
            pass

def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["system"] == "NebulaLab OS"

def test_prometheus_metrics(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "nebulalab" in res.text or "python" in res.text

def test_installer_scripts(client):
    res_sh = client.get("/join")
    assert res_sh.status_code == 200
    assert "nebulalab_agent" in res_sh.text

    res_ps1 = client.get("/join.ps1")
    assert res_ps1.status_code == 200
    assert "nebulalab_agent" in res_ps1.text

def test_machine_registration_and_list(client):
    payload = {
        "hostname": "api-test-node",
        "ip_address": "192.168.1.55",
        "os_type": "Pop!_OS",
        "cpu_cores": 8,
        "ram_total_gb": 32.0,
        "disk_total_gb": 512.0,
        "tags": "dev,test"
    }
    reg_res = client.post("/api/machines/register", json=payload)
    assert reg_res.status_code in [200, 201]
    data = reg_res.json()
    assert data["hostname"] == "api-test-node"
    node_id = data["id"]

    # List machines
    list_res = client.get("/api/machines")
    assert list_res.status_code == 200
    machines = list_res.json()
    assert any(m["id"] == node_id for m in machines)

def test_tags_endpoints(client):
    # Retrieve machine id
    machines = client.get("/api/machines").json()
    assert len(machines) > 0
    mid = machines[0]["id"]

    # Add tag
    add_tag_res = client.post(f"/api/machines/{mid}/tags", json={"tag": "api-tag"})
    assert add_tag_res.status_code == 200

    # Get all tags
    tags_res = client.get("/api/tags")
    assert tags_res.status_code == 200
    tags = tags_res.json()["tags"]
    assert "api-tag" in tags

    # Filter by tag
    by_tag_res = client.get("/api/machines/by-tag/api-tag")
    assert by_tag_res.status_code == 200
    assert len(by_tag_res.json()["machines"]) >= 1

    # Remove tag
    del_tag_res = client.delete(f"/api/machines/{mid}/tags/api-tag")
    assert del_tag_res.status_code == 200

def test_jobs_api_workflow(client):
    machines = client.get("/api/machines").json()
    mid = machines[0]["id"]

    # Create job
    job_payload = {
        "machine_id": mid,
        "command": "uptime",
        "job_type": "shell",
        "target": "specific"
    }
    create_res = client.post("/api/jobs", json=job_payload)
    assert create_res.status_code in [200, 201]
    job = create_res.json()
    job_id = job["id"]

    # Poll jobs for agent
    poll_res = client.get(f"/api/agent/{mid}/jobs/poll")
    assert poll_res.status_code == 200
    pending = poll_res.json()
    assert any(j["id"] == job_id for j in pending)

    # Agent update status
    update_res = client.post(
        f"/api/agent/{mid}/jobs/{job_id}/status",
        json={"status": "completed", "stdout": "up 2 days", "return_code": 0}
    )
    assert update_res.status_code == 200

    # Inspect job
    get_res = client.get(f"/api/jobs/{job_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "completed"

def test_files_upload_and_delete(client):
    filename = "test_artifact.txt"
    file_content = b"File content for NebulaLab cluster"

    # Upload
    files = {"file": (filename, file_content, "text/plain")}
    up_res = client.post("/api/files/upload", files=files, data={"encrypt": "false"})
    assert up_res.status_code in [200, 201]
    up_data = up_res.json()
    assert up_data["filename"] == filename

    # List files
    list_res = client.get("/api/files")
    assert list_res.status_code == 200
    files_list = list_res.json()
    assert any(f["filename"] == filename for f in files_list)

    # Download
    dl_res = client.get(f"/api/files/download/{filename}")
    assert dl_res.status_code == 200
    assert dl_res.content == file_content

    # Delete
    del_res = client.delete(f"/api/files/{filename}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "ok"

    # Verify deleted
    dl_res_after = client.get(f"/api/files/download/{filename}")
    assert dl_res_after.status_code == 404
