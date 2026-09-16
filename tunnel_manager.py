"""
Tunnel Manager for NebulaLab OS
Gère l'accès distant sécurisé sans aucune configuration complexe ni saisie d'adresses IP ou ports.
Fournit un accès HTTPS public instantané via :
- Mode 'auto' : Zéro token, zéro inscription (localhost.run / pinggy / serveo)
- Mode 'ngrok' : Support officiel ngrok avec authtoken si spécifié
- Mode 'localhost.run' : Tunnel SSH direct avec TLS automatique
- Mode 'pinggy' : Tunnel HTTPS Pinggy
- Mode 'serveo' : Tunnel SSH reverse Serveo
"""

import os
import sys
import re
import time
import signal
import socket
import logging
import asyncio
import subprocess
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] [Tunnel] %(message)s')
logger = logging.getLogger("nebulalab.tunnel")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ENV_FILE = os.path.join(BASE_DIR, ".env")
TUNNEL_URL_FILE = os.path.join(DATA_DIR, "tunnel_url.txt")
TUNNEL_PID_FILE = os.path.join(DATA_DIR, "tunnel.pid")
TUNNEL_LOG_FILE = os.path.join(DATA_DIR, "tunnel.log")


class TunnelManager:
    def __init__(self, port: int = 8000, provider: Optional[str] = None):
        self.port = port
        self.provider = (provider or os.getenv("TUNNEL_PROVIDER", "auto")).lower()
        self.ngrok_authtoken = os.getenv("NGROK_AUTHTOKEN", "").strip()
        self.public_url: Optional[str] = None
        self.active_provider: Optional[str] = None
        self.proc: Optional[subprocess.Popen] = None
        self.running = False
        self._keepalive_task: Optional[asyncio.Task] = None

        # Performance tracking
        self.start_time: Optional[float] = None
        self.reconnect_count: int = 0
        self.last_reconnect_time: Optional[float] = None
        # Provider success tracking for auto-mode improvement
        self.provider_success: Dict[str, Dict[str, Any]] = {}  # provider -> {success_count, total_attempts, last_success_time}
        self.provider_last_attempt: Dict[str, float] = {}      # provider -> last_attempt_timestamp

        os.makedirs(DATA_DIR, exist_ok=True)

        # Validate and potentially correct configuration
        self._validate_config()

    def _validate_config(self):
        """Valide la configuration et fournit des conseils d'amélioration, notamment pour ngrok"""
        valid_providers = ["auto", "ngrok", "localhost.run", "lhr", "pinggy", "serveo", "disabled", "none", "off", "false"]
        if self.provider not in valid_providers:
            logger.warning(f"Fournisseur de tunnel inconnu '{self.provider}'. Utilisation de 'auto' par défaut.")
            self.provider = "auto"

        # Guidance for ngrok
        if self.provider == "ngrok" and not self.ngrok_authtoken:
            logger.warning(
                "Fournisseur ngrok sélectionné mais aucun authtoken configuré. "
                "Pour utiliser ngrok, obtenez un token gratuit sur https://dashboard.ngrok.com/get-started/your-authtoken "
                "et définissez la variable d'environnement NGROK_AUTHTOKEN. "
                "En attendant, basculement automatique vers le mode 'zero-config' (localhost.run/pinggy/serveo)."
            )
            # Auto-fallback to zero-config mode for immediate usability
            self.provider = "auto"

        # Warn if disabled but user might expect tunneling
        if self.provider in ["disabled", "none", "off", "false"]:
            logger.info("Tunnel distant explicitement désactivé par configuration.")

    def _record_provider_attempt(self, provider: str, success: bool):
        """Enregistre une tentative d'utilisation d'un fournisseur pour améliorer la sélection automatique"""
        now = time.time()
        if provider not in self.provider_success:
            self.provider_success[provider] = {"success_count": 0, "total_attempts": 0, "last_success_time": None}
        if provider not in self.provider_last_attempt:
            self.provider_last_attempt[provider] = 0

        self.provider_success[provider]["total_attempts"] += 1
        self.provider_last_attempt[provider] = now
        if success:
            self.provider_success[provider]["success_count"] += 1
            self.provider_success[provider]["last_success_time"] = now

    def _get_best_auto_provider(self) -> str:
        """Détermine le meilleur fournisseur à essayer en mode auto selon l'historique"""
        # If we have no data, return the default order
        if not self.provider_success:
            return "localhost.run"  # Start with localhost.run as it's often reliable

        # Score each provider we have data on
        scored_providers = []
        for provider, stats in self.provider_success.items():
            total = stats["total_attempts"]
            if total == 0:
                success_rate = 0.0
            else:
                success_rate = stats["success_count"] / total

            # Factor in how recently it was attempted (prefer less recently attempted if success rate is low)
            last_attempt = self.provider_last_attempt.get(provider, 0)
            time_since_attempt = time.time() - last_attempt if last_attempt > 0 else float('inf')

            # Simple score: success rate weighted by recency (but favor higher success rate)
            # We'll use: score = success_rate * (1 + min(time_since_attempt / 3600, 1))
            # This gives a slight boost to providers not tried recently
            time_factor = min(time_since_attempt / 3600, 1.0)  # Cap at 1 hour
            score = success_rate * (1 + time_factor * 0.5)  # Up to 50% boost for not-tried-recently

            scored_providers.append((score, provider))

        # Also consider providers we haven't tried yet (they should have high priority)
        all_zero_config = ["localhost.run", "pinggy", "serveo"]
        for provider in all_zero_config:
            if provider not in self.provider_success:
                # Untried providers get a good score to encourage trying them
                scored_providers.append((0.8, provider))  # Arbitrary good score

        # Sort by score descending
        scored_providers.sort(key=lambda x: x[0], reverse=True)

        # Return the best provider
        if scored_providers:
            return scored_providers[0][1]
        else:
            return "localhost.run"  # Fallback

    def update_config(self, provider: Optional[str] = None, ngrok_authtoken: Optional[str] = None):
        """Met à jour les paramètres de configuration du tunnel en mémoire"""
        if provider is not None:
            self.provider = provider.strip().lower()
        if ngrok_authtoken is not None:
            self.ngrok_authtoken = ngrok_authtoken.strip()

    def save_config_to_env(self, provider: Optional[str] = None, ngrok_authtoken: Optional[str] = None):
        """Sauvegarde les paramètres de configuration dans le fichier .env"""
        self.update_config(provider, ngrok_authtoken)
        if not os.path.exists(ENV_FILE):
            return

        try:
            with open(ENV_FILE, "r") as f:
                lines = f.readlines()

            new_lines = []
            provider_set = False
            token_set = False

            for line in lines:
                if line.startswith("TUNNEL_PROVIDER="):
                    new_lines.append(f"TUNNEL_PROVIDER={self.provider}\n")
                    provider_set = True
                elif line.startswith("NGROK_AUTHTOKEN="):
                    new_lines.append(f"NGROK_AUTHTOKEN={self.ngrok_authtoken}\n")
                    token_set = True
                else:
                    new_lines.append(line)

            if not provider_set:
                new_lines.append(f"TUNNEL_PROVIDER={self.provider}\n")
            if not token_set:
                new_lines.append(f"NGROK_AUTHTOKEN={self.ngrok_authtoken}\n")

            with open(ENV_FILE, "w") as f:
                f.writelines(new_lines)
            logger.info("Configuration tunnel mise à jour dans .env")
        except Exception as e:
            logger.warning(f"Impossible d'écrire dans .env: {e}")

    def get_saved_url(self) -> Optional[str]:
        """Récupère l'URL publique sauvegardée si le tunnel est actif"""
        if os.path.exists(TUNNEL_URL_FILE):
            try:
                with open(TUNNEL_URL_FILE, "r") as f:
                    url = f.read().strip()
                    if url.startswith("http"):
                        return url
            except Exception:
                pass
        return self.public_url

    def _save_url(self, url: str):
        self.public_url = url
        try:
            with open(TUNNEL_URL_FILE, "w") as f:
                f.write(url)
        except Exception as e:
            logger.debug(f"Erreur sauvegarde URL tunnel: {e}")

    def _clear_url(self):
        self.public_url = None
        if os.path.exists(TUNNEL_URL_FILE):
            try:
                os.remove(TUNNEL_URL_FILE)
            except Exception:
                pass

    def start_ngrok(self) -> Optional[str]:
        """Démarre un tunnel via ngrok (si authtoken configuré ou pyngrok présent)"""
        try:
            from pyngrok import ngrok, conf
            if self.ngrok_authtoken:
                ngrok.set_auth_token(self.ngrok_authtoken)
            
            tunnel = ngrok.connect(self.port, "http")
            url = tunnel.public_url
            if url.startswith("http://"):
                url = url.replace("http://", "https://")
            self.active_provider = "ngrok"
            self._save_url(url)
            logger.info(f"✅ Tunnel Ngrok actif : {url}")
            return url
        except Exception as e:
            logger.warning(f"Impossible de démarrer Ngrok : {e}")
            return None

    def start_localhost_run(self) -> Optional[str]:
        """Démarre un tunnel SSH direct sans aucun compte via localhost.run (Zero-Config)"""
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=20",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-R", f"80:localhost:{self.port}",
            "nokey@localhost.run"
        ]
        return self._run_ssh_tunnel("localhost.run", cmd, r"https://[a-zA-Z0-9.-]+\.lhr\.life")

    def start_pinggy(self) -> Optional[str]:
        """Démarre un tunnel SSH direct sans compte via pinggy.io (Zero-Config)"""
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=20",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-p", "443",
            "-R", f"0:localhost:{self.port}",
            "a.pinggy.io"
        ]
        return self._run_ssh_tunnel(
            "pinggy",
            cmd,
            r"https://[a-zA-Z0-9.-]+\.(?:free\.pinggy\.net|pinggy\.link|run\.pinggy-free\.link|a\.pinggy\.online)"
        )

    def start_serveo(self) -> Optional[str]:
        """Démarre un tunnel SSH direct sans compte via serveo.net (Zero-Config)"""
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=20",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-R", f"80:localhost:{self.port}",
            "serveo.net"
        ]
        return self._run_ssh_tunnel("serveo", cmd, r"https://[a-zA-Z0-9.-]+(?:\.serveousercontent\.com|\.serveo\.net)")

    def _run_ssh_tunnel(self, provider_name: str, cmd: list, pattern: str) -> Optional[str]:
        """Lance la commande SSH et extrait l'URL HTTPS retournée"""
        try:
            self.stop()
            log_file = open(TUNNEL_LOG_FILE, "w")
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )

            start_time = time.time()
            found_url = None

            while time.time() - start_time < 12:
                if self.proc.poll() is not None:
                    break
                line = self.proc.stdout.readline()
                if line:
                    log_file.write(line)
                    log_file.flush()
                    match = re.search(pattern, line)
                    if match:
                        candidate = match.group(0)
                        if "dashboard.pinggy.io" not in candidate:
                            found_url = candidate
                            break
                else:
                    time.sleep(0.2)

            if found_url:
                self.active_provider = provider_name
                self._save_url(found_url)
                logger.info(f"✅ Tunnel {provider_name} actif : {found_url}")
                return found_url
            else:
                logger.warning(f"Échec obtention URL pour {provider_name}")
                if self.proc:
                    try:
                        self.proc.terminate()
                    except Exception:
                        pass
                return None
        except Exception as e:
            logger.warning(f"Erreur lancement tunnel {provider_name} : {e}")
            return None

    def start(self) -> Optional[str]:
        """Démarre le meilleur tunnel selon la configuration avec sélection intelligente en mode auto"""
        if self.provider in ["none", "disabled", "off", "false"]:
            logger.info("Tunnel distant désactivé par configuration.")
            return None

        logger.info(f"🌐 Initialisation du Tunnel d'accès distant (Mode: {self.provider})...")

        # 1. Si ngrok explicitement demandé ou token fourni
        if self.provider == "ngrok" or (self.provider == "auto" and self.ngrok_authtoken):
            url = self.start_ngrok()
            if url:
                self._record_provider_attempt("ngrok", True)
                self.running = True
                return url
            else:
                self._record_provider_attempt("ngrok", False)
                # Si ngrok échoue en mode auto, continuer avec les alternatives zéro-config
                if self.provider == "auto":
                    logger.info("Ngrok échoué, passage aux alternatives zéro-config...")
                else:
                    return None

        # 2. Mode auto avec sélection intelligente du fournisseur
        if self.provider == "auto":
            # Essayer dans l'ordre déterminé par l'intelligence basée sur l'historique
            providers_to_try = []

            # Ajouter les fournisseurs zéro-config selon leur score
            zero_config_providers = ["localhost.run", "pinggy", "serveo"]
            provider_scores = []

            for provider in zero_config_providers:
                if provider in self.provider_success:
                    total = self.provider_success[provider]["total_attempts"]
                    if total == 0:
                        success_rate = 0.0
                    else:
                        success_rate = self.provider_success[provider]["success_count"] / total

                    # Factor in recency
                    last_attempt = self.provider_last_attempt.get(provider, 0)
                    time_since_attempt = time.time() - last_attempt if last_attempt > 0 else float('inf')
                    time_factor = min(time_since_attempt / 3600, 1.0)  # Cap at 1 hour
                    score = success_rate * (1 + time_factor * 0.5)
                else:
                    # Untried providers get a good score
                    score = 0.8

                provider_scores.append((score, provider))

            # Trier par score décroissant
            provider_scores.sort(key=lambda x: x[0], reverse=True)
            providers_to_try = [provider for score, provider in provider_scores]

            logger.info(f"Ordre de tentative des fournisseurs zéro-config (basé sur l'historique) : {', '.join(providers_to_try)}")

            # Essayer chaque fournisseur dans l'ordre optimisé
            for provider in providers_to_try:
                url = None
                if provider == "localhost.run":
                    url = self.start_localhost_run()
                elif provider == "pinggy":
                    url = self.start_pinggy()
                elif provider == "serveo":
                    url = self.start_serveo()

                if url:
                    self._record_provider_attempt(provider, True)
                    self.running = True
                    return url
                else:
                    self._record_provider_attempt(provider, False)

            # Si tous les fournisseurs zéro-config échouent et qu'on a un token ngrok, essayer ngrok en dernier recours
            if self.ngrok_authtoken:
                logger.info("Tous les fournisseurs zéro-config ont échoué, tentative avec ngrok...")
                url = self.start_ngrok()
                if url:
                    self._record_provider_attempt("ngrok", True)
                    self.running = True
                    return url
                else:
                    self._record_provider_attempt("ngrok", False)

        # 3. Fournisseurs spécifiques (non-auto)
        if self.provider == "localhost.run" or self.provider == "lhr":
            url = self.start_localhost_run()
            if url:
                self._record_provider_attempt("localhost.run", True)
                self.running = True
                return url
            else:
                self._record_provider_attempt("localhost.run", False)

        if self.provider == "pinggy":
            url = self.start_pinggy()
            if url:
                self._record_provider_attempt("pinggy", True)
                self.running = True
                return url
            else:
                self._record_provider_attempt("pinggy", False)

        if self.provider == "serveo":
            url = self.start_serveo()
            if url:
                self._record_provider_attempt("serveo", True)
                self.running = True
                return url
            else:
                self._record_provider_attempt("serveo", False)

        logger.error("❌ Impossible d'initialiser un tunnel distant. L'accès local LAN reste 100% fonctionnel.")
        return None

    def stop(self):
        """Arrête le tunnel en cours"""
        self.running = False
        if self.active_provider == "ngrok" or self.provider == "ngrok":
            try:
                from pyngrok import ngrok
                ngrok.kill()
            except Exception:
                pass

        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

        self._clear_url()
        self.active_provider = None
        logger.info("Tunnel arrêté.")

    async def start_async_supervisor(self):
        """Superviseur asynchrone pour FastAPI/Uvicorn"""
        loop = asyncio.get_running_loop()
        url = await loop.run_in_executor(None, self.start)
        if url:
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        return url

    async def _keepalive_loop(self):
        """Vérifie que le tunnel reste ouvert et le relance si besoin"""
        while self.running:
            await asyncio.sleep(15)
            if self.active_provider != "ngrok" and self.proc:
                if self.proc.poll() is not None:
                    logger.warning("Tunnel déconnecté. Reconnexion automatique...")
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self.start)

    def get_status(self) -> Dict[str, Any]:
        """Retourne l'état complet du tunnel"""
        saved_url = self.get_saved_url()
        is_active = bool(saved_url and (self.running or (self.proc and self.proc.poll() is None)))
        return {
            "active": is_active,
            "provider": self.active_provider or self.provider,
            "configured_provider": self.provider,
            "has_ngrok_token": bool(self.ngrok_authtoken),
            "public_url": saved_url,
            "port": self.port,
            "zero_config": self.provider in ["auto", "localhost.run", "pinggy", "serveo"]
        }


# Instance singleton
tunnel_instance = TunnelManager()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    tm = TunnelManager()

    if action == "start":
        url = tm.start()
        if url:
            print(f"TUNNEL_URL={url}")
            try:
                while True:
                    time.sleep(5)
            except KeyboardInterrupt:
                tm.stop()
        else:
            sys.exit(1)
    elif action == "url":
        url = tm.get_saved_url()
        if url:
            print(url)
        else:
            print("NONE")
    elif action == "status":
        print(tm.get_status())
    elif action == "stop":
        tm.stop()
    elif action == "restart":
        tm.stop()
        time.sleep(1)
        url = tm.start()
        print(f"RESTARTED_TUNNEL_URL={url}")


if __name__ == "__main__":
    main()
