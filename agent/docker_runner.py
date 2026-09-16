"""
Docker Execution and Container Management for NebulaLab Agents.
"""
import asyncio
import logging
from typing import Tuple, List, Dict, Any

logger = logging.getLogger("nebulalab.agent.docker")


class DockerRunner:
    @staticmethod
    async def list_containers() -> List[Dict[str, Any]]:
        """Liste les conteneurs Docker présents sur la machine"""
        try:
            proc = await asyncio.create_subprocess_shell(
                "docker ps -a --format '{{json .}}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            import json
            containers = []
            for line in stdout.decode('utf-8', errors='ignore').splitlines():
                if line.strip():
                    containers.append(json.loads(line))
            return containers
        except Exception:
            return []

    @staticmethod
    async def run_container(image: str, command: str = "", timeout: float = 300.0) -> Tuple[str, str, int]:
        """Exécute un conteneur et capture stdout/stderr"""
        cmd = f"docker run --rm {image} {command}".strip()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
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
            return ("", "Timeout de l'exécution du conteneur", -1)
