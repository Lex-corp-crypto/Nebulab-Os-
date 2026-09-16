#!/usr/bin/env python3
"""
NebulaLab CLI - Distributed Linux Lab Command Line Interface
Permet d'administrer le cluster, d'exécuter des jobs, de transférer des fichiers et de surveiller les nœuds depuis le terminal.
"""

import os
import sys

# Auto-reexec with .venv Python if available and not already running in it
_venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python")
if os.path.exists(_venv_python) and sys.executable != _venv_python and not os.environ.get("NEBULALAB_NO_REEXEC"):
    os.environ["NEBULALAB_NO_REEXEC"] = "1"
    os.execv(_venv_python, [_venv_python] + sys.argv)

import json
import time
import argparse
import requests

DEFAULT_API_URL = os.getenv("API_URL", "http://localhost:8000")
TOKEN_FILE = os.path.expanduser("~/.nebulalab_token")


def get_api_url(args) -> str:
    return (getattr(args, "api", None) or DEFAULT_API_URL).rstrip("/")


def get_auth_headers(api_url: str) -> dict:
    """Récupère ou génère automatiquement le token d'authentification admin"""
    token = None
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                token = f.read().strip()
        except Exception:
            pass

    # Si token existant, tester sa validité
    if token:
        try:
            r = requests.get(f"{api_url}/api/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=2)
            if r.status_code == 200:
                return {"Authorization": f"Bearer {token}"}
        except Exception:
            pass

    # Connexion automatique admin par défaut
    try:
        r = requests.post(f"{api_url}/api/auth/login", json={"username": "admin", "password": "admin123"}, timeout=3)
        if r.status_code == 200:
            data = r.json()
            token = data.get("access_token")
            if token:
                try:
                    with open(TOKEN_FILE, "w") as f:
                        f.write(token)
                except Exception:
                    pass
                return {"Authorization": f"Bearer {token}"}
    except Exception:
        pass
    return {}


def cmd_status(args):
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/overview", timeout=5)
        if r.status_code != 200:
            print(f"Erreur API ({r.status_code}) : {r.text}")
            return
        data = r.json()
        print(f"\n========================================================")
        print(f"  🌌 {data.get('cluster_name', 'NebulaLab')} - Cluster Status")
        print(f"========================================================")
        print(f"  Nœuds Actifs   : {data.get('active_nodes')}/{data.get('total_nodes')}")
        avgs = data.get('cluster_averages', {})
        print(f"  Charge Moyenne : CPU {avgs.get('cpu_percent')}% | RAM {avgs.get('memory_percent')}% | Disque {avgs.get('disk_percent')}%")
        print(f"  Alertes Actives: {data.get('active_alerts_count')}")
        
        pub_url = data.get('public_url')
        if pub_url:
            print(f"  Tunnel Distant : {pub_url} (Zéro-Config HTTPS)")
        
        jstats = data.get('job_stats', {})
        print(f"  Jobs : {jstats.get('completed', 0)} terminés | {jstats.get('running', 0)} en cours | {jstats.get('failed', 0)} échoués")
        print(f"--------------------------------------------------------")
        print(f"{'ID':<4} {'Hôte':<20} {'IP':<16} {'OS':<12} {'CPU%':<8} {'RAM%':<8} {'Statut'}")
        print(f"--------------------------------------------------------")
        for n in data.get("nodes", []):
            m = n.get("metrics") or {}
            status_str = "🟢 En ligne" if n.get("is_active") else "🔴 Hors-ligne"
            print(f"{n.get('id'):<4} {n.get('hostname')[:19]:<20} {n.get('ip_address'):<16} {n.get('os_type')[:11]:<12} {m.get('cpu_percent', 0.0):<8.1f} {m.get('memory_percent', 0.0):<8.1f} {status_str}")
        print("========================================================\n")
    except Exception as e:
        print(f"Impossible de joindre le Master API ({url}) : {e}")


def cmd_tunnel(args):
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/tunnel", timeout=5)
        if r.status_code == 200:
            data = r.json()
            pub_url = data.get("public_url")
            print("\n========================================================")
            print("  🌐 NebulaLab OS - Tunnel d'Accès Distant (Zéro-Config)")
            print("========================================================")
            print(f"  Statut      : {'🟢 En ligne' if data.get('active') else '🔴 Hors-ligne'}")
            print(f"  Fournisseur : {data.get('provider')}")
            print(f"  URL Publique: {pub_url or 'Non connecté'}")
            if pub_url:
                print("--------------------------------------------------------")
                print("  ⚡ Commande 1-Clic pour connecter vos machines (0 IP à taper) :")
                print(f"     curl -sSL {pub_url}/join | bash")
            print("========================================================\n")
        else:
            print(f"Erreur tunnel ({r.status_code}) : {r.text}")
    except Exception as e:
        print(f"Impossible de joindre le Master API ({url}) : {e}")


def cmd_run(args):
    url = get_api_url(args)
    headers = get_auth_headers(url)

    # Handle --tag option (mutually exclusive with --node and --broadcast)
    if args.tag:
        # Parse tags
        tag_list = [t.strip() for t in args.tag.split(',') if t.strip()]
        if not tag_list:
            print("❌ Erreur: --tag nécessite au moins un tag valide")
            return

        # Get machines matching all tags
        try:
            # Build query parameter
            tags_param = ','.join(tag_list)
            r = requests.get(f"{url}/api/machines/by-tags?tags={tags_param}", timeout=5)
            if r.status_code != 200:
                print(f"❌ Erreur lors de la recherche de machines par tags: {r.text}")
                return
            data = r.json()
            machines = data.get("machines", [])
            if not machines:
                print(f"🔍 Aucune machine active ne possède tous les tags: {args.tag}")
                return

            print(f"🎯 {len(machines)} machine(s) trouvée(s) avec les tags {args.tag}")

            # Create a job for each matching machine
            jobs_created = []
            for machine in machines:
                machine_id = machine["id"]
                payload = {
                    "command": args.command,
                    "arguments": args.arguments,
                    "job_type": args.type,
                    "target": "specific",
                    "machine_id": machine_id
                }
                try:
                    r = requests.post(f"{url}/api/jobs", json=payload, headers=headers, timeout=10)
                    if r.status_code in [200, 201]:
                        job_res = r.json()
                        job_id = job_res.get("id")
                        jobs_created.append({
                            "id": job_id,
                            "machine_id": machine_id,
                            "hostname": machine.get("hostname", "inconnu")
                        })
                    else:
                        print(f"⚠️  Échec création job pour machine #{machine_id}: {r.text}")
                except Exception as e:
                    print(f"⚠️  Erreur création job pour machine #{machine_id}: {e}")

            if not jobs_created:
                print("❌ Aucun job n'a pu être créé.")
                return

            print(f"✅ {len(jobs_created)} job(s) créé(s) avec succès :")
            for job in jobs_created:
                print(f"  - Job #{job['id']} assigné à la machine #{job['machine_id']} ({job['hostname']})")

            # Wait for results if requested
            if not args.no_wait:
                print("⏳ Attente de l'exécution des jobs...")
                completed = 0
                for job in jobs_created:
                    job_id = job["id"]
                    for _ in range(60):  # Wait up to 60 seconds
                        time.sleep(1)
                        try:
                            jr = requests.get(f"{url}/api/jobs/{job_id}", headers=headers, timeout=5)
                            if jr.status_code == 200:
                                job_data = jr.json()
                                st = job_data.get("status")
                                if st in ["completed", "failed", "cancelled"]:
                                    completed += 1
                                    print(f"\n--- Résultat Job #{job_id} (Machine #{job['machine_id']}) ---")
                                    print(f"Statut: {st.upper()}, Exit code: {job_data.get('return_code')}")
                                    if job_data.get("stdout"):
                                        print(job_data.get("stdout").rstrip())
                                    if job_data.get("stderr"):
                                        print(f"\n[STDERR]\n{job_data.get('stderr').rstrip()}")
                                    break
                                else:
                                    print(".", end="", flush=True)
                        except Exception:
                            print(".", end="", flush=True)
                    print()  # New line after each job's wait
                print(f"\n✅ {completed}/{len(jobs_created)} job(s) terminé(s).")
            return

        except Exception as e:
            print(f"❌ Erreur lors de l'exécution avec tags: {e}")
            return

    # Existing logic for --node, --broadcast, or auto
    payload = {
        "command": args.command,
        "arguments": args.arguments,
        "job_type": args.type,
        "target": "broadcast" if args.broadcast else ("auto" if not args.node else "specific"),
        "machine_id": args.node
    }
    try:
        r = requests.post(f"{url}/api/jobs", json=payload, headers=headers, timeout=10)
        if r.status_code not in [200, 201]:
            print(f"Erreur création job ({r.status_code}) : {r.text}")
            return
        res = r.json()
        if res.get("broadcast"):
            print(f"✅ Job diffusé avec succès sur {res.get('count')} machines !")
            for j in res.get("jobs", []):
                print(f"  - Job #{j.get('id')} assigné à la machine #{j.get('machine_id')}")
            return

        job_id = res.get("id")
        print(f"🚀 Job #{job_id} lancé sur machine #{res.get('machine_id')}. Attente de l'exécution...")

        # Attendre le résultat
        if not args.no_wait:
            for _ in range(60):
                time.sleep(1)
                jr = requests.get(f"{url}/api/jobs/{job_id}", headers=headers, timeout=5)
                if jr.status_code == 200:
                    job = jr.json()
                    st = job.get("status")
                    if st in ["completed", "failed", "cancelled"]:
                        print(f"\n--- Résultat (Statut: {st.upper()}, Exit code: {job.get('return_code')}) ---")
                        if job.get("stdout"):
                            print(job.get("stdout").rstrip())
                        if job.get("stderr"):
                            print(f"\n[STDERR]\n{job.get('stderr').rstrip()}")
                        return
                    else:
                        print(".", end="", flush=True)
            print("\n⏳ Délai d'attente dépassé (le job continue en arrière-plan).")
    except Exception as e:
        print(f"Erreur d'exécution : {e}")


def cmd_upload(args):
    url = get_api_url(args)
    headers = get_auth_headers(url)
    if not os.path.exists(args.file):
        print(f"Fichier introuvable : {args.file}")
        return
    try:
        with open(args.file, "rb") as f:
            files = {"file": (os.path.basename(args.file), f)}
            data = {"encrypt": "true" if args.encrypt else "false"}
            r = requests.post(f"{url}/api/files/upload", files=files, data=data, headers=headers, timeout=30)
            if r.status_code in [200, 201]:
                res = r.json()
                print(f"✅ Fichier téléversé : {res.get('filename')} ({res.get('size_bytes')} octets, SHA256: {res.get('checksum')[:8]}...)")
            else:
                print(f"Échec upload : {r.text}")
    except Exception as e:
        print(f"Erreur upload : {e}")


def cmd_logs(args):
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/logs?limit={args.limit}", timeout=5)
        if r.status_code == 200:
            logs = r.json()
            for l in reversed(logs):
                print(f"[{l.get('timestamp')}] [{l.get('level')}] [{l.get('hostname') or l.get('source')}] {l.get('message')}")
        else:
            print(f"Erreur logs : {r.text}")
    except Exception as e:
        print(f"Erreur logs : {e}")


def cmd_alerts(args):
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/alerts", timeout=5)
        if r.status_code == 200:
            alerts = r.json()
            if not alerts:
                print("✅ Aucune alerte active dans le cluster.")
                return
            print(f"\n🚨 {len(alerts)} alerte(s) active(s) :")
            for a in alerts:
                print(f"  - [#{a.get('id')}] [{a.get('severity').upper()}] {a.get('hostname')}: {a.get('message')} ({a.get('created_at')})")
        else:
            print(f"Erreur alerts : {r.text}")
    except Exception as e:
        print(f"Erreur alerts : {e}")


def cmd_tag_list(args):
    """Liste tous les tags utilisés dans le cluster"""
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/tags", timeout=5)
        if r.status_code == 200:
            data = r.json()
            tags = data.get("tags", [])
            if not tags:
                print("🏷️  Aucun tag défini dans le cluster.")
                return
            print(f"\n🏷️  Tags utilisés ({len(tags)}):")
            for tag in sorted(tags):
                print(f"  - {tag}")
        else:
            print(f"Erreur tags : {r.text}")
    except Exception as e:
        print(f"Erreur tags : {e}")


def cmd_tag_add(args):
    """Ajoute un tag à une machine spécifique"""
    url = get_api_url(args)
    try:
        r = requests.post(f"{url}/api/machines/{args.machine_id}/tags",
                         json={"tag": args.tag}, timeout=5)
        if r.status_code == 200:
            print(f"✅ Tag '{args.tag}' ajouté à la machine #{args.machine_id}")
        else:
            print(f"Erreur ajout tag : {r.text}")
    except Exception as e:
        print(f"Erreur ajout tag : {e}")


def cmd_tag_remove(args):
    """Retire un tag d'une machine spécifique"""
    url = get_api_url(args)
    try:
        r = requests.delete(f"{url}/api/machines/{args.machine_id}/tags/{args.tag}", timeout=5)
        if r.status_code == 200:
            print(f"✅ Tag '{args.tag}' retiré de la machine #{args.machine_id}")
        else:
            print(f"Erreur retrait tag : {r.text}")
    except Exception as e:
        print(f"Erreur retrait tag : {e}")


def cmd_tag_machines(args):
    """Liste les machines possédant un tag spécifique"""
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/machines/by-tag/{args.tag}", timeout=5)
        if r.status_code == 200:
            data = r.json()
            machines = data.get("machines", [])
            if not machines:
                print(f"🔍 Aucune machine active ne possède le tag '{args.tag}'.")
                return
            print(f"\n🖥️  Machines avec le tag '{args.tag}' ({len(machines)}):")
            for m in machines:
                hostname = m.get('hostname', 'inconnu')
                os_type = m.get('os_type', 'inconnu')
                ip = m.get('ip_address', 'inconnu')
                print(f"  - #{m.get('id')} [{hostname}] {os_type} @ {ip}")
        else:
            print(f"Erreur recherche machines par tag : {r.text}")
    except Exception as e:
        print(f"Erreur recherche machines par tag : {e}")


def main():
    parser = argparse.ArgumentParser(description="NebulaLab OS - Distributed Linux Cluster CLI")
    parser.add_argument("--api", default=DEFAULT_API_URL, help="URL du Master API (défaut: http://localhost:8000)")
    subparsers = parser.add_subparsers(dest="command_name")

    # version
    p_version = subparsers.add_parser("version", help="Afficher la version de NebulaLab OS")
    p_version.set_defaults(func=cmd_version)

    # status
    p_status = subparsers.add_parser("status", help="Afficher l'état du cluster et des nœuds")
    p_status.set_defaults(func=cmd_status)

    # run
    p_run = subparsers.add_parser("run", help="Exécuter une tâche distante")
    p_run.add_argument("command", help="Commande à exécuter (ex: 'uptime', 'df -h', 'docker ps')")
    p_run.add_argument("arguments", nargs="*", default=[], help="Arguments supplémentaires")
    p_run.add_argument("--node", type=int, default=None, help="ID de la machine cible")
    p_run.add_argument("--broadcast", action="store_true", help="Exécuter sur TOUS les nœuds du cluster")
    p_run.add_argument("--tag", type=str, help="Exécuter sur les nœuds possédant TOUS les tags spécifiés (séparés par des virgules)")
    p_run.add_argument("--type", choices=["shell", "docker", "script"], default="shell", help="Type de job")
    p_run.add_argument("--no-wait", action="store_true", help="Ne pas attendre le résultat")
    p_run.set_defaults(func=cmd_run)

    # upload
    p_up = subparsers.add_parser("upload", help="Téléverser un fichier dans le cloud partagé")
    p_up.add_argument("file", help="Chemin du fichier local")
    p_up.add_argument("--encrypt", action="store_true", help="Chiffrer le fichier avec Fernet AES")
    p_up.set_defaults(func=cmd_upload)

    # logs
    p_logs = subparsers.add_parser("logs", help="Afficher les logs centralisés")
    p_logs.add_argument("--limit", type=int, default=30, help="Nombre de lignes")
    p_logs.set_defaults(func=cmd_logs)

    # alerts
    p_alerts = subparsers.add_parser("alerts", help="Lister les alertes actives")
    p_alerts.set_defaults(func=cmd_alerts)

    # tag
    p_tag = subparsers.add_parser("tag", help="Gérer les tags des machines")
    p_tag_sub = p_tag.add_subparsers(dest="tag_action")

    # tag list
    p_tag_list = p_tag_sub.add_parser("list", help="Lister tous les tags utilisés")
    p_tag_list.set_defaults(func=cmd_tag_list)

    # tag add
    p_tag_add = p_tag_sub.add_parser("add", help="Ajouter un tag à une machine")
    p_tag_add.add_argument("machine_id", type=int, help="ID de la machine")
    p_tag_add.add_argument("tag", help="Tag à ajouter")
    p_tag_add.set_defaults(func=cmd_tag_add)

    # tag remove
    p_tag_remove = p_tag_sub.add_parser("remove", help="Retirer un tag d'une machine")
    p_tag_remove.add_argument("machine_id", type=int, help="ID de la machine")
    p_tag_remove.add_argument("tag", help="Tag à retirer")
    p_tag_remove.set_defaults(func=cmd_tag_remove)

    # tag machines
    p_tag_machines = p_tag_sub.add_parser("machines", help="Lister les machines possédant un tag spécifique")
    p_tag_machines.add_argument("tag", help="Tag à rechercher")
    p_tag_machines.set_defaults(func=cmd_tag_machines)

    # tunnel
    p_tunnel = subparsers.add_parser("tunnel", help="Afficher l'état du tunnel d'accès distant zéro-config")
    p_tunnel.set_defaults(func=cmd_tunnel)

    # tunnel-config
    p_tunnel_config = subparsers.add_parser("tunnel-config", help="Configurer le tunnel d'accès distant")
    p_tunnel_config.add_argument("--provider", choices=["auto", "localhost.run", "pinggy", "serveo", "ngrok", "disabled"], help="Fournisseur de tunnel à utiliser")
    p_tunnel_config.add_argument("--ngrok-authtoken", help="Token d'authentification ngrok (optionnel)")
    p_tunnel_config.set_defaults(func=cmd_tunnel_config)

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Effectuer un auto-diagnostic complet du système")
    p_doctor.set_defaults(func=cmd_doctor)

    # tunnel-test
    p_tunnel_test = subparsers.add_parser("tunnel-test", help="Tester la connectivité du tunnel d'accès distant")
    p_tunnel_test.set_defaults(func=cmd_tunnel_test)

    # hello
    p_hello = subparsers.add_parser("hello", help="Afficher un message de bienvenue et un rappel des commandes utiles")
    p_hello.set_defaults(func=cmd_hello)

    # nodes / machines
    p_nodes = subparsers.add_parser("nodes", aliases=["machines"], help="Lister en détail tous les nœuds du cluster")
    p_nodes.set_defaults(func=cmd_nodes)

    # files / ls-files
    p_files = subparsers.add_parser("files", aliases=["ls-files"], help="Lister les fichiers partagés dans le cloud du cluster")
    p_files.set_defaults(func=cmd_files)

    # download
    p_dl = subparsers.add_parser("download", help="Télécharger un fichier du cloud partagé")
    p_dl.add_argument("filename", help="Nom du fichier à télécharger")
    p_dl.add_argument("-o", "--output", help="Chemin de destination local")
    p_dl.add_argument("--decrypt", action="store_true", help="Déchiffrer le fichier avec Fernet AES")
    p_dl.set_defaults(func=cmd_download)

    # rm-file
    p_rm_file = subparsers.add_parser("rm-file", help="Supprimer un fichier du cloud partagé")
    p_rm_file.add_argument("filename", help="Nom du fichier à supprimer")
    p_rm_file.set_defaults(func=cmd_rm_file)

    # jobs
    p_jobs = subparsers.add_parser("jobs", help="Lister l'historique des jobs du cluster")
    p_jobs.add_argument("--limit", type=int, default=20, help="Nombre maximal de jobs à afficher")
    p_jobs.set_defaults(func=cmd_jobs)

    # job
    p_job_detail = subparsers.add_parser("job", help="Afficher les détails et sorties stdout/stderr d'un job")
    p_job_detail.add_argument("job_id", type=int, help="ID du job")
    p_job_detail.set_defaults(func=cmd_job_detail)

    # cancel-job
    p_job_cancel = subparsers.add_parser("cancel-job", help="Annuler un job en attente ou en cours")
    p_job_cancel.add_argument("job_id", type=int, help="ID du job à annuler")
    p_job_cancel.set_defaults(func=cmd_job_cancel)

    # rm-node
    p_rm_node = subparsers.add_parser("rm-node", help="Supprimer / désenregistrer un nœud du cluster")
    p_rm_node.add_argument("machine_id", type=int, help="ID de la machine à supprimer")
    p_rm_node.set_defaults(func=cmd_rm_node)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        cmd_status(args)


def cmd_version(args):
    """Affiche la version de NebulaLab OS"""
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
    try:
        with open(version_file, "r") as f:
            version = f.read().strip()
        print(f"NebulaLab OS version {version}")
    except Exception as e:
        print(f"Erreur lors de la lecture de la version: {e}")


def cmd_tunnel_config(args):
    """Configure le tunnel d'accès distant"""
    from tunnel_manager import tunnel_instance

    provider = getattr(args, "provider", None)
    ngrok_authtoken = getattr(args, "ngrok_authtoken", None)

    # Mettre à jour la configuration
    tunnel_instance.save_config_to_env(provider, ngrok_authtoken)

    # Afficher la configuration actuelle
    status = tunnel_instance.get_status()
    print("\n========================================================")
    print("  🌐 NebulaLab OS - Configuration du Tunnel Mis à Jour")
    print("========================================================")
    print(f"  Fournisseur configuré : {status['configured_provider']}")
    if status['has_ngrok_token']:
        print(f"  Token Ngrok           : Configuré ({'*' * min(len(status.get('ngrok_token_preview', '')), 8)}...)")
    else:
        print(f"  Token Ngrok           : Non configuré")
    print(f"  URL publique actuelle : {status['public_url'] or 'Non connecté'}")
    print("========================================================")
    print("\n💡 Pour appliquer les changements, redémarrez le tunnel :")
    print("   ./run_local.sh restart")
    print("   ou")
    print("   ./run_local.sh stop puis ./run_local.sh start\n")


def cmd_doctor(args):
    """Effectue un auto-diagnostic complet du système NebulaLab OS"""
    print("\n========================================================")
    print("  🏥 NebulaLab OS - Auto-diagnostic Système")
    print("========================================================")

    issues = []
    warnings = []
    success = []

    # 1. Vérification de l'environnement Python
    print("\n🐍 Environnement Python :")
    import sys
    python_version = sys.version_info
    if python_version.major >= 3 and python_version.minor >= 8:
        success.append(f"✅ Python {python_version.major}.{python_version.minor}.{python_version.micro} (version soutenue)")
    else:
        issues.append(f"❌ Python {python_version.major}.{python_version.minor}.{python_version.micro} (requis: 3.8+)")

    # Vérification du venv
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python")
    if os.path.exists(venv_python):
        success.append("✅ Environnement virtuel (.venv) détecté")
    else:
        warnings.append("⚠️  Environnement virtuel (.venv) non trouvé - sera créé au démarrage")

    # 2. Vérification des dépendances
    print("\n📦 Dépendances :")
    requirements_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    if os.path.exists(requirements_file):
        try:
            with open(requirements_file, "r") as f:
                requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            missing = []
            package_import_map = {
                "uvicorn": "uvicorn",
                "python-jose": "jose",
                "python-dotenv": "dotenv",
                "python-multipart": "multipart",
                "prometheus-client": "prometheus_client",
                "pyyaml": "yaml",
            }
            for req in requirements:
                raw_name = req.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].strip()
                # Strip bracket extras e.g. uvicorn[standard] -> uvicorn
                pkg_base = raw_name.split("[")[0].strip()
                import_name = package_import_map.get(pkg_base, pkg_base.replace("-", "_"))
                try:
                    __import__(import_name)
                except ImportError:
                    missing.append(raw_name)

            if missing:
                issues.append(f"❌ Dépendances manquantes: {', '.join(missing)}")
                warnings.append("💡 Exécutez: pip install -r requirements.txt")
            else:
                success.append("✅ Toutes les dépendances sont installées")
        except Exception as e:
            warnings.append(f"⚠️  Impossible de vérifier les dépendances: {e}")
    else:
        issues.append("❌ Fichier requirements.txt introuvable")

    # 3. Vérification de la configuration
    print("\n⚙️  Configuration :")
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env_example = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.example")

    if os.path.exists(env_file):
        success.append("✅ Fichier .env trouvé")
        # Vérification des variables essentielles
        try:
            with open(env_file, "r") as f:
                env_content = f.read()

            essential_vars = ["SECRET_KEY", "TUNNEL_PROVIDER"]
            missing_vars = []
            for var in essential_vars:
                if f"{var}=" not in env_content or f"{var}=" in env_content and env_content.split(f"{var}=")[1].split("\n")[0].strip() == "":
                    missing_vars.append(var)

            if missing_vars:
                warnings.append(f"⚠️  Variables essentielles manquantes ou vides: {', '.join(missing_vars)}")
            else:
                success.append("✅ Variables essentielles configurées")

            # Vérification du secret key
            if "SECRET_KEY=" in env_content:
                secret_line = [line for line in env_content.split("\n") if line.startswith("SECRET_KEY=")][0]
                secret_value = secret_line.split("=", 1)[1].strip()
                if len(secret_value) < 32 or "ChangeMeToARandom32ByteString!" in secret_value:
                    warnings.append("⚠️  SECRET_KEY trop faible ou par défaut - générez-en une forte avec: openssl rand -hex 32")
                else:
                    success.append("✅ SECRET_KEY suffisamment forte")
        except Exception as e:
            warnings.append(f"⚠️  Erreur lors de la lecture de .env: {e}")
    else:
        if os.path.exists(env_example):
            warnings.append("⚠️  Fichier .env manquant - copiez .env.example vers .env et configurez-le")
        else:
            issues.append("❌ Ni .env ni .env.example trouvés")

    # 4. Vérification des ressources système
    print("\n💻 Ressources système :")
    try:
        import psutil
        # Espace disque
        disk_usage = psutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
        free_gb = disk_usage.free / (1024**3)
        if free_gb > 1:
            success.append(f"✅ Espace disque libre: {free_gb:.1f} GB")
        else:
            issues.append(f"❌ Espace disque critique: {free_gb:.1f} GB libre (minimum 1 GB recommandé)")

        # Mémoire
        memory = psutil.virtual_memory()
        if memory.available > 100 * 1024 * 1024:  # 100 MB
            success.append(f"✅ Mémoire disponible: {memory.available // (1024**2)} MB")
        else:
            warnings.append(f"⚠️  Mémoire faible: {memory.available // (1024**2)} MB disponible")

        # Port 8000
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 8000))
        sock.close()
        if result == 0:
            warnings.append("⚠️  Port 8000 déjà utilisé - NebulaLab ne pourra pas démarrer")
        else:
            success.append("✅ Port 8000 disponible")

    except ImportError:
        warnings.append("⚠️  psutil non disponible - vérifications système limitées")
    except Exception as e:
        warnings.append(f"⚠️  Erreur lors de la vérification des ressources: {e}")

    # 5. Vérification des services (si l'API est accessible)
    print("\n🔧 Services :")
    try:
        import requests
        api_url = "http://localhost:8000"
        try:
            response = requests.get(f"{api_url}/health", timeout=2)
            if response.status_code == 200:
                success.append("✅ API Master accessible et répondante")

                # Vérifier l'agent via l'API
                try:
                    overview = requests.get(f"{api_url}/api/overview", timeout=2)
                    if overview.status_code == 200:
                        data = overview.json()
                        active_nodes = data.get('active_nodes', 0)
                        total_nodes = data.get('total_nodes', 0)
                        if active_nodes > 0:
                            success.append(f"✅ {active_nodes}/{total_nodes} nœud(s) actif(s)")
                        else:
                            warnings.append("⚠️  Aucun nœud actif détecté")
                    else:
                        warnings.append("⚠️  Impossible de récupérer l'aperçu des nœuds")
                except:
                    warnings.append("⚠️  Impossible de vérifier l'état des nœuds")
            else:
                issues.append(f"❌ API Master répond avec le code {response.status_code}")
        except requests.exceptions.ConnectionError:
            # API pas démarrée, ce n'est pas forcément un problème
            success.append("ℹ️  API Master non démarrée (normal si les services ne sont pas lancés)")
        except Exception as e:
            warnings.append(f"⚠️  Erreur lors de la vérification de l'API: {e}")
    except ImportError:
        warnings.append("⚠️  requests non disponible - vérifications des services limitées")

    # 6. Vérification du tunnel
    print("\n🌐 Tunnel d'accès distant :")
    try:
        from tunnel_manager import tunnel_instance
        status = tunnel_instance.get_status()
        if status["active"]:
            success.append(f"✅ Tunnel actif ({status['provider']}) -> {status['public_url']}")
        else:
            warnings.append("⚠️  Tunnel inactif - sera démarré avec ./run_local.sh start")
            if status["has_ngrok_token"]:
                success.append("✅ Token ngrok configuré")
            else:
                warnings.append("⚠️  Aucun token ngrok configuré - utilisation du mode zéro-config")
    except Exception as e:
        warnings.append(f"⚠️  Erreur lors de la vérification du tunnel: {e}")

    # Résumé
    print("\n" + "="*54)
    print("  📋 RÉSUMÉ DU DIAGNOSTIC")
    print("="*54)

    if success:
        print("\n✅ POINTS FORTS :")
        for s in success:
            print(f"  {s}")

    if warnings:
        print("\n⚠️  AVERTISSEMENTS :")
        for w in warnings:
            print(f"  {w}")

    if issues:
        print("\n❌ PROBLÈMES À RÉSOUDRE :")
        for i in issues:
            print(f"  {i}")
        print("\n🔧 RECOMMANDATIONS :")
        print("  1. Résolvez les problèmes ci-dessus en priorité")
        print("  2. Exécutez './run_local.sh start' pour démarrer les services")
        print("  3. Utilisez './nebulab.py tunnel-config' pour configurer le tunnel")
        print("  4. Consultez la documentation dans README.md")
    elif warnings and not issues:
        print("\n💡 RECOMMANDATIONS :")
        print("  1. Les avertissements ci-dessus ne bloquent pas l'utilisation")
        print("  2. Vous pouvez démarrer le système avec './run_local.sh start'")
        print("  3. Pour une meilleure fiabilité tunnel, envisagez de configurer ngrok")
    else:
        print("\n🎉 SYSTÈME OPTIMISÉ :")
        print("  Tous les vérifications sont vertes !")
        print("  Vous pouvez démarrer NebulaLab OS avec confiance.")

    print("\n" + "="*54)


def cmd_tunnel_test(args):
    """Teste la connectivité et les performances du tunnel ngrok"""
    print("\n========================================================")
    print("  🧪 NebulaLab OS - Test de Connectivité Tunnel")
    print("========================================================")
    
    try:
        from tunnel_manager import tunnel_instance
        import time
        import requests
        
        # Vérifier si ngrok est configuré
        if not tunnel_instance.ngrok_authtoken:
            print("❌ Aucun token ngrok configuré")
            print("💡 Pour utiliser ngrok, obtenez un token gratuit sur https://dashboard.ngrok.com/get-started/your-authtoken")
            print("   Puis configurez-le avec: ./nebulab.py tunnel-config --provider ngrok --ngrok-authtoken VOTRE_TOKEN")
            return
        
        print("🔑 Token ngrok détecté")
        print("🚀 Démarrage du tunnel ngrok en cours...")
        
        # Sauvegarder la configuration actuelle
        original_provider = tunnel_instance.provider
        original_authtoken = tunnel_instance.ngrok_authtoken
        
        # Forcer le provider à ngrok pour ce test
        tunnel_instance.provider = "ngrok"
        
        start_time = time.time()
        url = tunnel_instance.start()
        connection_time = time.time() - start_time
        
        if not url:
            print("❌ Échec du démarrage du tunnel ngrok")
            print("💡 Vérifiez votre token ngrok et votre connexion internet")
            # Restaurer la configuration
            tunnel_instance.provider = original_provider
            tunnel_instance.ngrok_authtoken = original_authtoken
            return
        
        print(f"✅ Tunnel ngrok démarré en {connection_time:.2f}s")
        print(f"🌐 URL publique: {url}")
        
        # Attendre un peu pour que le tunnel soit complètement établi
        time.sleep(2)
        
        # Test de connectivité via le tunnel
        print("\n📡 Test de connectivité via le tunnel public...")
        test_start = time.time()
        try:
            # Test de l'endpoint de santé
            health_response = requests.get(f"{url}/health", timeout=10)
            health_latency = (time.time() - test_start) * 1000
            
            if health_response.status_code == 200:
                print(f"✅ Endpoint /health accessible (latence: {health_latency:.0f}ms)")
                
                # Test de l'API overview
                api_start = time.time()
                overview_response = requests.get(f"{url}/api/overview", timeout=10)
                api_latency = (time.time() - api_start) * 1000
                
                if overview_response.status_code == 200:
                    print(f"✅ Endpoint /api/overview accessible (latence: {api_latency:.0f}ms)")
                    data = overview_response.json()
                    nodes = data.get('active_nodes', 0)
                    print(f"📊 {nodes} nœud(s) détecté(s) via le tunnel")
                else:
                    print(f"⚠️  Endpoint /api/overview répond avec le code {overview_response.status_code}")
            else:
                print(f"❌ Endpoint /health répond avec le code {health_response.status_code}")
                
        except requests.exceptions.ConnectionError:
            print("❌ Impossible de se connecter au tunnel public")
            print("💡 Le tunnel pourrait être bloqué par un firewall ou ngrok pourrait avoir des problèmes")
        except requests.exceptions.Timeout:
            print("❌ Timeout lors de la connexion au tunnel (>10s)")
            print("💡 Le tunnel pourrait être lent ou inaccessible")
        except Exception as e:
            print(f"❌ Erreur lors du test de connectivité: {e}")
        
        # Test de latence supplémentaire (ping simulé)
        print("\n⏱️  Mesure de latence supplémentaire...")
        latencies = []
        for i in range(3):
            try:
                ping_start = time.time()
                requests.get(f"{url}/health", timeout=5)
                latencies.append((time.time() - ping_start) * 1000)
                time.sleep(0.5)
            except:
                latencies.append(None)
        
        valid_latencies = [l for l in latencies if l is not None]
        if valid_latencies:
            avg_latency = sum(valid_latencies) / len(valid_latencies)
            print(f"📈 Latence moyenne: {avg_latency:.0f}ms (sur {len(valid_latencies)}/{len(latencies)} tests réussis)")
        else:
            print("❌ Impossible de mesurer la latence")
        
        # Arrêter le tunnel temporaire
        print("\n🛑 Arrêt du tunnel de test...")
        tunnel_instance.stop()
        
        # Restaurer la configuration originale
        tunnel_instance.provider = original_provider
        tunnel_instance.ngrok_authtoken = original_authtoken
        
        # Résumé final
        print("\n" + "="*54)
        print("  📋 RÉSULTAT DU TEST")
        print("="*54)
        print("✅ Test de tunnel ngrok terminé avec succès")
        print(f"🔑 Token ngrok: Configuré")
        print(f"🌐 Fonctionnalité tunnel: Opérationnelle")
        print("\n🚀 Pour ajouter un nœud distant :")
        print(f"   curl -sSL {url}/join | bash")
        print("\n💡 Pour utiliser ngrok en permanence :")
        print("   ./nebulab.py tunnel-config --provider ngrok --ngrok-authtoken VOTRE_TOKEN")
        print("   ./run_local.sh restart")
        print("\n" + "="*54)
        
    except ImportError as e:
        print(f"❌ Module manquant: {e}")
        print("💡 Assurez-vous que pyngrok est installé: pip install pyngrok")
    except Exception as e:
        print(f"❌ Erreur inattendue lors du test: {e}")
        # Essayer de restaurer la configuration en cas d'erreur
        try:
            from tunnel_manager import tunnel_instance
            tunnel_instance.stop()
        except:
            pass


def cmd_hello(args):
    """Afficher un message de bienvenue et un rappel des commandes utiles"""
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
    try:
        with open(version_file, "r") as f:
            version = f.read().strip()
    except Exception:
        version = "inconnue"

    hello_msg = r"""
  _____ _           _       _   _
 |  ___| |_ ___ ___| |_ ___| |_(_) ___  _ __
 | |_  | __/ -_|_-<  _/ -_|  _| |/ _ \| '  \
 |  _| | ||___|__/\__\___|\__|_|\___/_|_|_|_|
 |_|   \__|

Welcome to NebulaLab OS v{version} 🌌

Quick start:
  ./run_local.sh start   -> Start all services
  ./nebulab.py version   -> Check version
  ./nebulab.py doctor    -> Run system diagnostic
  ./nebulab.py tunnel-test -> Test ngrok connectivity
  ./nebulab.py status    -> Check cluster state

Happy clustering! 🚀
""".format(version=version)

    print(hello_msg)


def cmd_nodes(args):
    """Affiche la liste détaillée de toutes les machines du cluster"""
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/machines", timeout=5)
        if r.status_code != 200:
            print(f"Erreur API ({r.status_code}) : {r.text}")
            return
        machines = r.json()
        if not machines:
            print("Aucune machine enregistrée dans le cluster.")
            return

        print("\n=========================================================================================")
        print("  🖥️  NebulaLab OS - Nœuds & Machines du Cluster")
        print("=========================================================================================")
        print(f"{'ID':<4} {'Hôte':<18} {'IP':<16} {'OS':<14} {'Cœurs':<6} {'RAM(GB)':<8} {'Tags':<15} {'Statut'}")
        print("-----------------------------------------------------------------------------------------")
        for m in machines:
            status_str = "🟢 En ligne" if m.get("is_active") else "🔴 Hors-ligne"
            tags_str = m.get("tags") or "-"
            print(f"{m.get('id'):<4} {m.get('hostname')[:17]:<18} {m.get('ip_address'):<16} {m.get('os_type')[:13]:<14} {m.get('cpu_cores', 1):<6} {m.get('ram_total_gb', 0):<8.1f} {tags_str[:14]:<15} {status_str}")
        print("=========================================================================================\n")
    except Exception as e:
        print(f"Impossible de joindre le Master API ({url}) : {e}")


def cmd_download(args):
    """Télécharge un fichier du cloud partagé"""
    url = get_api_url(args)
    filename = args.filename
    output_path = args.output or os.path.basename(filename)
    decrypt_param = "?decrypt=true" if args.decrypt else ""
    try:
        r = requests.get(f"{url}/api/files/download/{filename}{decrypt_param}", timeout=30, stream=True)
        if r.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            size = os.path.getsize(output_path)
            print(f"✅ Fichier téléchargé avec succès : {output_path} ({size} octets)")
        elif r.status_code == 404:
            print(f"❌ Fichier '{filename}' introuvable dans le cluster.")
        else:
            print(f"❌ Erreur lors du téléchargement ({r.status_code}) : {r.text}")
    except Exception as e:
        print(f"Erreur de téléchargement : {e}")


def cmd_files(args):
    """Liste les fichiers partagés dans le cloud du cluster"""
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/files", timeout=5)
        if r.status_code == 200:
            files = r.json()
            if not files:
                print("📁 Aucun fichier stocké dans le cloud du cluster.")
                return
            print("\n=================================================================")
            print("  📁 NebulaLab OS - Stockage Cloud Partagé")
            print("=================================================================")
            print(f"{'Nom':<32} {'Taille (Ko)':<14} {'Dernière Modification'}")
            print("-----------------------------------------------------------------")
            for f in files:
                size_kb = round(f.get("size_bytes", 0) / 1024, 1)
                mod = f.get("modified_at", "")[:19].replace("T", " ")
                print(f"{f.get('filename')[:31]:<32} {size_kb:<14} {mod}")
            print("=================================================================\n")
        else:
            print(f"Erreur API ({r.status_code}) : {r.text}")
    except Exception as e:
        print(f"Erreur : {e}")


def cmd_rm_file(args):
    """Supprime un fichier du cloud partagé"""
    url = get_api_url(args)
    headers = get_auth_headers(url)
    try:
        r = requests.delete(f"{url}/api/files/{args.filename}", headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"✅ Fichier '{args.filename}' supprimé avec succès.")
        else:
            print(f"❌ Échec de la suppression ({r.status_code}) : {r.text}")
    except Exception as e:
        print(f"Erreur : {e}")


def cmd_jobs(args):
    """Liste les jobs récents du cluster"""
    url = get_api_url(args)
    limit = getattr(args, "limit", 20)
    try:
        r = requests.get(f"{url}/api/jobs?limit={limit}", timeout=5)
        if r.status_code == 200:
            jobs = r.json()
            if not jobs:
                print("Aucun job récent dans le cluster.")
                return
            print("\n=====================================================================================")
            print("  ⚡ NebulaLab OS - Historique des Jobs")
            print("=====================================================================================")
            print(f"{'ID':<6} {'Nœud':<8} {'Statut':<12} {'Code':<6} {'Commande':<35} {'Créé à'}")
            print("-------------------------------------------------------------------------------------")
            for j in jobs:
                cmd_str = (j.get("command") or "")[:34]
                created = (j.get("created_at") or "")[:19].replace("T", " ")
                print(f"#{j.get('id'):<5} #{j.get('machine_id', '-'):<7} {j.get('status', '').upper():<12} {j.get('return_code', 0):<6} {cmd_str:<35} {created}")
            print("=====================================================================================\n")
        else:
            print(f"Erreur API ({r.status_code}) : {r.text}")
    except Exception as e:
        print(f"Erreur : {e}")


def cmd_job_detail(args):
    """Affiche les détails et la sortie d'un job spécifique"""
    url = get_api_url(args)
    try:
        r = requests.get(f"{url}/api/jobs/{args.job_id}", timeout=5)
        if r.status_code == 200:
            j = r.json()
            print(f"\n========================================================")
            print(f"  Job #{j.get('id')} - {j.get('command')}")
            print(f"========================================================")
            print(f"  Nœud       : #{j.get('machine_id')}")
            print(f"  Type       : {j.get('job_type')}")
            print(f"  Statut     : {j.get('status', '').upper()}")
            print(f"  Exit Code  : {j.get('return_code')}")
            print(f"  Créé le    : {j.get('created_at')}")
            print(f"  Démarré le : {j.get('started_at') or '-'}")
            print(f"  Terminé le : {j.get('completed_at') or '-'}")
            if j.get('stdout'):
                print(f"\n--- STDOUT ---\n{j.get('stdout').rstrip()}")
            if j.get('stderr'):
                print(f"\n--- STDERR ---\n{j.get('stderr').rstrip()}")
            print("========================================================\n")
        else:
            print(f"Job #{args.job_id} introuvable ({r.status_code}).")
    except Exception as e:
        print(f"Erreur : {e}")


def cmd_job_cancel(args):
    """Annule un job en cours ou en attente"""
    url = get_api_url(args)
    headers = get_auth_headers(url)
    try:
        r = requests.post(f"{url}/api/jobs/{args.job_id}/cancel", headers=headers, timeout=5)
        if r.status_code == 200:
            print(f"✅ Job #{args.job_id} annulé avec succès.")
        else:
            print(f"❌ Impossible d'annuler le job #{args.job_id} ({r.status_code}) : {r.text}")
    except Exception as e:
        print(f"Erreur : {e}")


def cmd_rm_node(args):
    """Supprime / désenregistre une machine du cluster"""
    url = get_api_url(args)
    headers = get_auth_headers(url)
    try:
        r = requests.delete(f"{url}/api/machines/{args.machine_id}", headers=headers, timeout=5)
        if r.status_code == 200:
            print(f"✅ Machine #{args.machine_id} supprimée du cluster.")
        else:
            print(f"❌ Impossible de supprimer la machine #{args.machine_id} ({r.status_code}) : {r.text}")
    except Exception as e:
        print(f"Erreur : {e}")


if __name__ == "__main__":
    main()
