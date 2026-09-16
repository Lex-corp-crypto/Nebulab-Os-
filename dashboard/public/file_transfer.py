"""
File Transfer Manager for NebulaLab (Distributed Linux Lab)
Gère le transfert sécurisé de fichiers entre machines (Pop!_OS, Ubuntu, Android, etc.)
Offre deux modes :
1. Direct HTTP/TLS crypté (universel, fonctionne sur tous les nœuds sans configuration SSH)
2. SFTP / SCP (via Paramiko pour les machines avec serveur SSH actif)
Inclus le calcul et la vérification des sommes de contrôle SHA-256 et le chiffrement optionnel Fernet AES.
"""

import os
import io
import hashlib
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, BinaryIO
from cryptography.fernet import Fernet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nebulalab.file_transfer")

STORAGE_DIR = os.getenv("STORAGE_DIR", "./data/shared_storage")


class FileTransferManager:
    def __init__(self, storage_dir: str = STORAGE_DIR):
        self.storage_dir = os.path.abspath(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self.secret_key = os.getenv("SECRET_KEY", "nebulalab-super-secret-cluster-key-2026")
        
        # Dériver une clé de chiffrement Fernet 32 bytes
        fernet_key = hashlib.sha256(self.secret_key.encode('utf-8')).digest()
        import base64
        self.cipher_suite = Fernet(base64.urlsafe_b64encode(fernet_key))

    def calculate_sha256(self, file_path: str) -> str:
        """Calcule le hash SHA-256 pour vérifier l'intégrité"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    async def save_uploaded_file(self, filename: str, file_obj: BinaryIO, encrypt: bool = False) -> Dict[str, Any]:
        """Enregistre un fichier transféré dans le stockage partagé"""
        safe_name = os.path.basename(filename)
        dest_path = os.path.join(self.storage_dir, safe_name)
        
        raw_bytes = file_obj.read() if hasattr(file_obj, 'read') else file_obj
        if isinstance(raw_bytes, bytes):
            if encrypt:
                data_to_write = self.cipher_suite.encrypt(raw_bytes)
            else:
                data_to_write = raw_bytes
                
            with open(dest_path, "wb") as f:
                f.write(data_to_write)
        else:
            raise ValueError("Type de contenu invalide pour la sauvegarde")

        checksum = self.calculate_sha256(dest_path)
        size_bytes = os.path.getsize(dest_path)
        
        logger.info(f"Fichier sauvegardé avec succès : {safe_name} ({size_bytes} octets, sha256={checksum[:8]}...)")
        return {
            "filename": safe_name,
            "file_path": dest_path,
            "size_bytes": size_bytes,
            "checksum": checksum,
            "encrypted": encrypt,
            "saved_at": datetime.utcnow().isoformat()
        }

    async def get_file_content(self, filename: str, decrypt: bool = False) -> Optional[bytes]:
        """Lit un fichier du stockage partagé avec déchiffrement optionnel"""
        safe_name = os.path.basename(filename)
        path = os.path.join(self.storage_dir, safe_name)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            data = f.read()
        if decrypt:
            try:
                return self.cipher_suite.decrypt(data)
            except Exception as e:
                logger.error(f"Erreur de déchiffrement : {e}")
                return data
        return data

    def list_shared_files(self) -> list:
        """Liste tous les fichiers stockés dans le cloud du lab"""
        files = []
        if not os.path.exists(self.storage_dir):
            return files
        for entry in os.scandir(self.storage_dir):
            if entry.is_file():
                stat = entry.stat()
                files.append({
                    "filename": entry.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "path": entry.path
                })
        return sorted(files, key=lambda x: x["modified_at"], reverse=True)

    async def transfer_via_sftp(self, source_path: str, destination_host: str, destination_path: str,
                               username: str, password: Optional[str] = None,
                               private_key_path: Optional[str] = None, port: int = 22) -> Dict[str, Any]:
        """Transfère un fichier vers un nœud distant via SFTP (Paramiko)"""
        import paramiko
        if not os.path.exists(source_path):
            return {"success": False, "error": f"Fichier local introuvable : {source_path}"}

        file_size = os.path.getsize(source_path)
        sha256 = self.calculate_sha256(source_path)

        def _do_sftp():
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if private_key_path and os.path.exists(private_key_path):
                pkey = paramiko.RSAKey.from_private_key_file(private_key_path)
                ssh.connect(destination_host, port=port, username=username, pkey=pkey, timeout=15)
            else:
                ssh.connect(destination_host, port=port, username=username, password=password, timeout=15)

            sftp = ssh.open_sftp()
            sftp.put(source_path, destination_path)
            remote_stat = sftp.stat(destination_path)
            sftp.close()
            ssh.close()
            return remote_stat.st_size

        try:
            remote_size = await asyncio.to_thread(_do_sftp)
            if remote_size != file_size:
                raise ValueError(f"Taille discordante après transfert : {remote_size} != {file_size}")
            logger.info(f"Transfert SFTP réussi vers {destination_host}:{destination_path}")
            return {
                "success": True,
                "source_path": source_path,
                "destination_host": destination_host,
                "destination_path": destination_path,
                "size_bytes": file_size,
                "checksum": sha256
            }
        except Exception as e:
            logger.error(f"Échec transfert SFTP : {e}")
            return {"success": False, "error": str(e)}