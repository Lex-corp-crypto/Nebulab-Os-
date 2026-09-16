"""
Job Manager for NebulaLab (Distributed Linux Lab)
Gère l'orchestration des jobs distribués, les priorités et la distribution sur les nœuds.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.job_manager")


class JobManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    async def create_job(self, job_data: dict) -> Dict[str, Any]:
        """
        Crée un job. Si machine_id == 0 ou None, distribue sur la machine la moins chargée.
        Si target == 'broadcast', crée un job pour TOUTES les machines actives du cluster !
        """
        try:
            target = job_data.get("target", "specific")
            
            if target == "broadcast":
                machines = await self.db_manager.get_all_machines()
                active_machines = [m for m in machines if m.get("is_active")]
                if not active_machines:
                    # Si aucune machine active, cibler quand même toutes les machines
                    active_machines = machines

                created_jobs = []
                for m in active_machines:
                    single_job = dict(job_data)
                    single_job["machine_id"] = m["id"]
                    job = await self.db_manager.create_job(single_job)
                    created_jobs.append(job)
                logger.info(f"Jobs broadcast créés sur {len(created_jobs)} machines")
                return {"broadcast": True, "count": len(created_jobs), "jobs": created_jobs}

            if target == "tag" or ("tag" in job_data and job_data["tag"]) or ("tags" in job_data and job_data["tags"]):
                raw_tags = job_data.get("tags") or job_data.get("tag")
                if isinstance(raw_tags, str):
                    tag_list = [t.strip() for t in raw_tags.split(",") if t.strip()]
                elif isinstance(raw_tags, list):
                    tag_list = [str(t).strip() for t in raw_tags if str(t).strip()]
                else:
                    tag_list = []

                if not tag_list:
                    raise ValueError("Cible par tag sélectionnée mais aucun tag valide fourni")

                machines = await self.db_manager.get_machines_by_tags(tag_list)
                if not machines:
                    raise ValueError(f"Aucune machine active ne possède les tags : {', '.join(tag_list)}")

                created_jobs = []
                for m in machines:
                    single_job = dict(job_data)
                    single_job["machine_id"] = m["id"]
                    job = await self.db_manager.create_job(single_job)
                    created_jobs.append(job)
                logger.info(f"Jobs créés pour {len(created_jobs)} machines avec les tags {tag_list}")
                return {"broadcast": True, "count": len(created_jobs), "jobs": created_jobs, "tags": tag_list}

            # Machine spécifique ou auto-load balance
            machine_id = job_data.get("machine_id")
            if not machine_id:
                # Choisir la machine avec le moins de CPU/charge
                latest_metrics = await self.db_manager.get_latest_metrics_for_all()
                if latest_metrics:
                    # Trier par cpu_percent
                    best = min(latest_metrics, key=lambda x: x.get("cpu_percent", 100))
                    machine_id = best["machine_id"]
                else:
                    machines = await self.db_manager.get_all_machines()
                    if machines:
                        machine_id = machines[0]["id"]
                    else:
                        raise ValueError("Aucune machine disponible dans le cluster")

            job_payload = dict(job_data)
            job_payload["machine_id"] = machine_id
            job = await self.db_manager.create_job(job_payload)
            logger.info(f"Job #{job['id']} créé pour la machine #{machine_id} (cmd: {job.get('command')})")
            return job
        except Exception as e:
            logger.error(f"Erreur lors de la création du job : {e}")
            raise

    async def get_job(self, job_id: int) -> Optional[dict]:
        return await self.db_manager.get_job(job_id)

    async def get_jobs(self, skip: int = 0, limit: int = 100, machine_id: Optional[int] = None) -> List[dict]:
        return await self.db_manager.get_jobs(skip=skip, limit=limit, machine_id=machine_id)

    async def get_pending_jobs(self, machine_id: int) -> List[dict]:
        return await self.db_manager.get_pending_jobs_for_machine(machine_id)

    async def update_job_status(self, job_id: int, status: str, stdout: str = "", stderr: str = "", return_code: int = 0) -> bool:
        try:
            await self.db_manager.update_job_status(job_id, status, stdout, stderr, return_code)
            logger.info(f"Job #{job_id} mis à jour : statut={status}, return_code={return_code}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du statut du job {job_id} : {e}")
            return False

    async def cancel_job(self, job_id: int) -> bool:
        job = await self.get_job(job_id)
        if not job:
            return False
        if job["status"] in ["completed", "failed", "cancelled"]:
            return False
        await self.db_manager.update_job_status(job_id, "cancelled", stderr="Cancelled by user")
        return True

    async def get_statistics(self) -> Dict[str, Any]:
        jobs = await self.get_jobs(limit=1000)
        return {
            "total": len(jobs),
            "pending": len([j for j in jobs if j.get("status") == "pending"]),
            "running": len([j for j in jobs if j.get("status") == "running"]),
            "completed": len([j for j in jobs if j.get("status") == "completed"]),
            "failed": len([j for j in jobs if j.get("status") == "failed"]),
            "cancelled": len([j for j in jobs if j.get("status") == "cancelled"]),
        }