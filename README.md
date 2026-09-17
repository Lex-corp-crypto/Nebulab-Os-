# 🌌 NebulaLab OS (Distributed Linux Lab & HomeLab Cloud)

📖 **English version** | **Version française** : [Cliquez ici](#french-version)

**NebulaLab OS** is a complete and modern platform for orchestration, monitoring, and distributed execution for heterogeneous multi-device clusters (**LINUX**, **Ubuntu**, **Windows**, **Android/Termux**, **iOS**, **Raspberry Pi**, **Debian** and Docker containers).

---
## ⚡ Developed & Integrated Features

| Feature | Description & Implementation |
| :--- | :--- |
| **🔍 Automatic Discovery** | Zero-config local network detection via **mDNS / Zeroconf** (`_nebulalab._tcp.local.`) and **Broadcast UDP** (port 5354) to instantly connect your machines without entering IP addresses. |
| **📊 Real‑time Monitoring** | Continuous telemetry of CPU (global and per core), RAM, Disk (`/` or `C:\`), Network Throughput (Rx/Tx) and Load Average with visual gauges and dynamic graphs. |
| **📁 File Transfer & Cloud** | Shared storage in the cluster, direct upload from PC or smartphone (photos, files, scripts), SHA‑256 integrity check, AES‑128 Fernet encryption and SFTP fallback. |
| **⚡ Execution & Job System** | Asynchronous task engine: Shell commands (`bash`, `sh`, `PowerShell`, `CMD`), multi‑line scripts, and Docker container execution (`docker run`). Supports specific targeting, simultaneous broadcast across the cluster, or automatic load‑balancing to the least‑loaded machine. |
| **🔐 Authentication & Security** | Password hashing with **bcrypt**, signed access tokens **JWT** (HS256) and role‑based permissions. |
| **📱 Web & Mobile Dashboard (PWA)** | Modern cyber‑dark ultra‑responsive interface adapted for computers, tablets and smartphones. PWA support (installation on mobile home screen as a native full‑screen app). |
| **📡 Real‑time WebSocket Flows** | Instant bidirectional synchronization of metrics, logs, job outputs and alerts. |
| **📜 Centralized Logs** | Collection and live streaming of event logs from all nodes with search filters and severity levels. |
| **🚨 Alerts & Notifications** | Proactive detection of CPU, RAM, Disk overloads and offline nodes with anti‑spam system (cooldown) and Webhook dispatch (Discord, Slack, ntfy) / WebSocket. |
| **🐳 Docker Orchestration** | Monitoring and execution of isolated tasks in Docker containers on each node. |
| **🔌 REST API & Prometheus** | REST endpoints documented via Swagger OpenAPI (`/docs`) and Prometheus metrics exporter (`/metrics`). |

---
## 🖥️ Multi‑Device Cluster Topology

You can run **3 or 4 devices (and even more)** simultaneously:

```
       ┌─────────────────────────────────────────────────────────┐
       │             🌌 NebulaLab Core API (Master)              │
       │       FastAPI • WebSocket • PostgreSQL / SQLite         │
       └────────────────────────────┬────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┼────────────────────────────┐
       │                            │                            │                            │
┌──────▼───────┐             ┌──────▼───────┐             ┌──────▼───────┐             ┌──────▼───────┐
│  any linux PC  │             │  Ubuntu PC   │             │  Smartphone  │             │  PC Windows  │
│  (Node #1)   │             │  (Node #2)   │             │ (PWA/Termux) │             │ (PowerShell) │
│ Master/Agent │             │ Agent Daemon │             │  (Node #3)   │             │  (Node #4)   │
└──────────────┘             └──────────────┘             └──────────────┘             └──────────────┘
```
---
## 🚀 Quick Start in 1 Command (On your Linux PC – example: Pop!_OS)

### Option A: Instant Local Launch (Zero‑Docker)
To start immediately the Master API, the Web interface and the local Agent:

```bash
cd /home/lex_luthor/distributed_linux_lab
./run_local.sh
```

- 💻 **Web Dashboard**: [http://localhost:8000](http://localhost:8000)
- 🌐 **Zero‑Config Remote Access (HTTPS)**: Automatically generated (via localhost.run / pinggy or Ngrok if configured) – 0 account, 0 IP and 0 port to configure!
- 📱 **Phone Access**: Open the tunnel URL or scan the QR code displayed in the dashboard
- 📖 **Swagger API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- 👤 **Default Credentials**: Username `admin` / Password `admin123`

---
### Option B: Full Deployment with Docker Compose
For a deployment with PostgreSQL, Redis, Prometheus and the Master:

```bash
docker compose up -d
```
---
## 🧪 Quick Connection Guide (Zero IP Entry / Zero Port)

### 1. Device #1: ANY LINUX PC (Master + Main Node)
On your Master PC:
```bash
./run_local.sh
```
*The terminal immediately shows the local URL and the secure public HTTPS URL.*

---
### 2. Device #2: Ubuntu / Debian / Pop!_OS PC (Client Nodes)
On any other Linux machine (anywhere in the world or on the local LAN):

```bash
# Via Zero‑Config Remote Tunnel (No IP to enter):
curl -sSL https://<YOUR_TUNNEL_URL>/join | bash

# OR on local Wi‑Fi:
curl -sSL http://<PC_IP>:8000/join | bash
```
*Your machine appears instantly on the dashboard with its OS badge and live CPU/RAM/Disk gauges!*

---
### 3. Device #3: Smartphones (Android / iPhone)

#### 📱 Mode A: Mobile Web Console & PWA (Touch & Full Screen)
1. Open your smartphone’s browser.
2. Go to the tunnel URL (or scan the **QR Code** in the **Mobile Access** tab of the dashboard on your PC).
3. Tap **"Add to Home Screen"** in the browser options.
4. You can now manage everything from your smartphone: monitor gauges, launch jobs and send files to the shared cloud!

#### 📱 Mode B: Turn your Smartphone into a Compute Node (Termux)
On an Android phone with the **Termux** app:
```bash
pkg update -y && pkg install -y curl
curl -sSL https://<YOUR_TUNNEL_URL>/join | bash
```
*Your smartphone appears in the cluster as an active compute node with the green Android badge!*

---
### 4. Device #4: Windows 10 / 11 PC (Windows Node)

#### 🪟 PowerShell Method (One Command)
On your Windows machine, open **PowerShell**:
```powershell
irm https://<YOUR_TUNNEL_URL>/join.ps1 | iex
```
*Your Windows PC appears in the cluster with the official blue Windows icon and you can send remote commands to it!*
---
## 🛠️ Command‑Line Interface (CLI `nebulalab.py`)

The command `./nebulalab.py` simplifies administration from your terminal:

```bash
# 1. Check global cluster and node status
./nebulalab.py status

# 2. Run a command on a specific node (e.g. machine #1 or #2)
./nebulalab.py run --node 1 "uname -a"
./nebulalab.py run --node 2 "free -m"

# 3. Broadcast a command to ALL nodes in the cluster at once
./nebulalab.py run --broadcast "df -h /"
./nebulalab.py run --broadcast "uptime"
./nebulalab.py run --broadcast "docker ps"

# 4. Upload an encrypted file to the shared cloud storage
./nebulalab.py upload ./mon_fichier.tar.gz --encrypt

# 5. View centralised logs in real time
./nebulalab.py logs --limit 20

# 6. List active alerts
./nebulalab.py alerts
```
---
## 📂 Complete Directory Structure & Role of Folders

```
distributed_linux_lab/
├── main_api.py            # Master REST API & Orchestrator FastAPI + WebSocket
├── agent_service.py       # Universal Agent daemon (Pop!_OS, Ubuntu, Windows, Android)
├── database.py            # Hybrid DB manager (PostgreSQL & SQLite auto‑fallback)
├── auth_manager.py        # JWT authentication & secure bcrypt hashing
├── job_manager.py         # Planner and manager of distributed jobs
├── alerting_system.py     # Alert rules engine and webhooks
├── file_transfer.py       # AES encrypted transfer, SHA‑256 and shared storage
├── service_discovery.py   # Automatic mDNS / Zeroconf & Broadcast UDP discovery
├── websocket_manager.py   # Real‑time WebSocket manager
├── health_checker.py      # Cluster health checker
├── nebulalab.py           # Cluster administration CLI
├── run_local.sh           # Quick local launch script (1 command)
├── install_agent.sh       # Automatic installation script for remote nodes
│
├── agent/                 # Agent module: per‑core telemetry & Docker runner
├── alerts/                # Alerts module: Discord/Slack/ntfy webhook notifiers
├── api/                   # API module: Pydantic schemas & validation
├── auth/                  # Auth module: security utilities & JWT signatures
├── file_transfer/         # Files module: encryption engine & SFTP
├── monitoring/            # Monitoring: Prometheus configuration & alert_rules.yml
├── nginx/                 # Nginx: reverse proxy & WebSocket proxy configuration
├── service_discovery/     # Network: mDNS listeners & broadcast UDP
│
├── dashboard/
│   ├── public/
│   │   ├── index.html     # High‑performance Web & Mobile PWA interface
│   │   └── manifest.json  # PWA configuration for smartphones
│   ├── src/app.js         # JavaScript client SDK / WebSocket
│   ├── styles/custom.css  # Cyber‑dark & glassmorphism styles
│   ├── server.js          # Optional Node.js server
│   └── package.json
│
├── docker-compose.yml     # Multi‑container deployment for the Master
├── docker-compose.agent.yml # Containerised deployment for remote nodes
├── Dockerfile.api         # Docker image of the Master API
├── Dockerfile.agent       # Docker image of the Agent
└── requirements.txt       # Python dependencies
```
---
## 🔒 Security & Encryption

- **Communications & API**: Bearer JWT authentication for all sensitive actions with configurable expiration.
- **Cloud Storage**: Symmetric **Fernet AES‑128** encryption to secure files uploaded to the shared storage.
- **Data Integrity**: Automatic **SHA‑256** fingerprint calculation to validate every inter‑machine transfer.
- **Local Network**: Shared signing keys to authenticate UDP/mDNS discovery announcements.

<a name="french-version"></a>
# 🌌 NebulaLab OS (Distributed Linux Lab & HomeLab Cloud)

**NebulaLab OS** est une plateforme complète et moderne d'orchestration, de surveillance et d'exécution distribuée pour clusters multi-appareils hétérogènes (**LINUX**, **Ubuntu**, **Windows**, **Android/Termux**, **iOS**, **Raspberry Pi**, **Debian** et conteneurs **Docker**).

---
## ⚡ Fonctionnalités Développées & Intégrées

| Fonctionnalité | Description & Implémentation |
| :--- | :--- |
| **🔍 Découverte Automatique** | Détection réseau local zéro-configuration via **mDNS / Zeroconf** (`_nebulalab._tcp.local.`) et **Broadcast UDP** (port 5354) pour connecter instantanément vos machines sans saisir d'adresses IP. |
| **📊 Monitoring Temps Réel** | Télémétrie continue CPU (global et par cœur), RAM, Disque (`/` ou `C:\`), Débit Réseau (Rx/Tx) et Load Average avec jauges visuelles et graphiques dynamiques. |
| **📁 Transfert de Fichiers & Cloud** | Stockage partagé dans le cluster, upload direct depuis PC ou smartphone (photos, fichiers, scripts), calcul d'intégrité **SHA-256**, chiffrement **AES-128 Fernet** et fallback SFTP. |
| **⚡ Exécution & Système de Jobs** | Moteur de tâches asynchrone : commandes Shell (`bash`, `sh`, `PowerShell`, `CMD`), scripts multi-lignes, et exécution de conteneurs Docker (`docker run`). Supporte le ciblage spécifique, le **Broadcast simultané sur tout le cluster**, ou l'équilibrage automatique sur la machine la moins chargée. |
| **🔐 Authentification & Sécurité** | Chiffrement des mots de passe avec **bcrypt**, jetons d'accès **JWT signés** (HS256) et permissions basées sur les rôles. |
| **📱 Dashboard Web & Mobile (PWA)** | Interface cyber-dark moderne, ultra-réactive, adaptée aux ordinateurs, tablettes et smartphones. Prise en charge **PWA** (installation sur l'écran d'accueil mobile comme une application native plein écran). |
| **📡 Flux WebSocket Temps Réel** | Synchronisation instantanée bidirectionnelle des métriques, des logs, des sorties de jobs et des alertes. |
| **📜 Logs Centralisés** | Collecte et streaming en direct des journaux d'événements de tous les nœuds avec filtres de recherche et niveaux de sévérité. |
| **🚨 Alertes & Notifications** | Détection proactive des surcharges CPU, RAM, Disque et des nœuds hors-ligne avec système anti-spam (cooldown) et dispatch Webhook (Discord, Slack, ntfy) / WebSocket. |
| **🐳 Orchestration Docker** | Monitoring et exécution de tâches isolées dans des conteneurs Docker sur chaque nœud. |
| **🔌 API REST & Prometheus** | Endpoints REST documentés via Swagger OpenAPI (`/docs`) et exportateur de métriques au format Prometheus (`/metrics`). |
---
## 🖥️ Topologie du Cluster Multi-Appareils

Vous pouvez faire tourner vos **3 ou 4 appareils (et bien plus) tous en même temps** :

```
       ┌─────────────────────────────────────────────────────────┐
       │             🌌 NebulaLab Core API (Master)              │
       │       FastAPI • WebSocket • PostgreSQL / SQLite         │
       └────────────────────────────┬────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┼────────────────────────────┐
       │                            │                            │                            │
┌──────▼───────┐             ┌──────▼───────┐             ┌──────▼───────┐             ┌──────▼───────┐
│  any linux PC  │             │  Ubuntu PC   │             │  Smartphone  │             │  PC Windows  │
│  (Nœud #1)   │             │  (Nœud #2)   │             │ (PWA/Termux) │             │ (PowerShell) │
│ Master/Agent │             │ Agent Daemon │             │  (Nœud #3)   │             │  (Nœud #4)   │
└──────────────┘             └──────────────┘             └──────────────┘             └──────────────┘
```
---
## 🚀 Démarrage Rapide en 1 Commande (Sur votre PC Linux – exemple : Pop!_OS)

### Option A : Lancement Local Instantané (Zero-Docker)
Pour démarrer immédiatement le Master API, l'interface Web et l'Agent local :

```bash
cd /home/lex_luthor/distributed_linux_lab
./run_local.sh
```

- 💻 **Dashboard Web** : [http://localhost:8000](http://localhost:8000)
- 🌐 **Accès Distant Zéro-Config (HTTPS)** : Généré automatiquement (via localhost.run / pinggy ou Ngrok si configuré) - 0 compte, 0 IP et 0 port à configurer !
- 📱 **Accès Téléphone** : Ouvrez l'URL du tunnel ou scannez le QR code affiché dans le dashboard
- 📖 **Documentation Swagger API** : [http://localhost:8000/docs](http://localhost:8000/docs)
- 👤 **Identifiants par défaut** : Nom d'utilisateur `admin` / Mot de passe `admin123`

---
### Option B : Déploiement Complet avec Docker Compose
Pour un déploiement avec PostgreSQL, Redis, Prometheus et le Master :

```bash
docker compose up -d
```
---
## 🧪 Guide de Connexion Rapide (Zéro Saisie d'IP / Zéro Port)

### 1. Appareil #1 : PC sous Linux (exemple : Pop!_OS) (Master + Nœud Principal)
Sur votre PC Master :
```bash
./run_local.sh
```
*Le terminal vous affiche immédiatement l'URL locale et l'URL publique sécurisée HTTPS.*

---
### 2. Appareil #2 : PC sous Ubuntu / Debian / Pop!_OS (Nœuds Clients)
Sur n'importe quelle autre machine Linux (partout dans le monde ou sur le réseau local) :

```bash
# Via le Tunnel Distant Zéro-Config (Aucune IP à entrer) :
curl -sSL https://<VOTRE_URL_TUNNEL>/join | bash

# OU sur le réseau local Wi-Fi :
curl -sSL http://<IP_DU_PC>:8000/join | bash
```
*Votre machine apparaît instantanément sur le dashboard avec son badge OS et ses jauges CPU/RAM/Disque en direct !*

---
### 3. Appareil #3 : Smartphones (Android / iPhone)

#### 📱 Mode A : Console Mobile Web & PWA (Tactile & Plein Écran)
1. Ouvrez le navigateur de votre smartphone.
2. Allez sur l'URL du tunnel (ou scannez le **QR Code** dans l'onglet **Accès Mobile** du dashboard sur votre PC).
3. Cliquez sur **"Ajouter à l'écran d'accueil"** dans les options du navigateur.
4. Vous pouvez tout administrer depuis votre smartphone : surveiller les jauges, lancer des jobs et envoyer des fichiers dans le cloud partagé !

#### 📱 Mode B : Transformer votre Smartphone en Nœud de Calcul (Termux)
Sur un téléphone Android avec l'application **Termux** :
```bash
pkg update -y && pkg install -y curl
curl -sSL https://<VOTRE_URL_TUNNEL>/join | bash
```
*Votre smartphone apparaît dans le cluster comme un nœud de calcul actif avec le badge vert Android !*

---
### 4. Appareil #4 : PC sous Windows 10 / 11 (Nœud Windows)

#### 🪟 Méthode PowerShell (1 Seule Commande)
Sur votre machine Windows, ouvrez **PowerShell** :
```powershell
irm https://<VOTRE_URL_TUNNEL>/join.ps1 | iex
```
*Le PC Windows apparaît dans le cluster avec l'icône Windows officielle bleue et vous pouvez lui envoyer des commandes à distance !*
---
## 🛠️ Utilisation de la Ligne de Commande (CLI `nebulalab.py`)

La commande `./nebulalab.py` simplifie l'administration depuis votre terminal :

```bash
# 1. Vérifier l'état global du cluster et des nœuds
./nebulalab.py status

# 2. Exécuter une commande sur un nœud précis (ex: machine #1 ou #2)
./nebulalab.py run --node 1 "uname -a"
./nebulalab.py run --node 2 "free -m"

# 3. Diffuser une commande sur TOUT le cluster en même temps (Broadcast simultané)
./nebulalab.py run --broadcast "df -h /"
./nebulalab.py run --broadcast "uptime"
./nebulalab.py run --broadcast "docker ps"

# 4. Téléverser un fichier chiffré dans le stockage cloud du cluster
./nebulalab.py upload ./mon_fichier.tar.gz --encrypt

# 5. Consulter les logs centralisés en direct
./nebulalab.py logs --limit 20

# 6. Lister les alertes actives
./nebulalab.py alerts
```
---
## 📂 Structure Complète et Rôle des Dossiers

```
distributed_linux_lab/
├── main_api.py            # Master REST API & Orchestrateur FastAPI + WebSocket
├── agent_service.py       # Démon Agent universel (Pop!_OS, Ubuntu, Windows, Android)
├── database.py            # Gestionnaire DB hybride (PostgreSQL & SQLite auto-fallback)
├── auth_manager.py        # Authentification JWT & Hachage sécurisé bcrypt
├── job_manager.py         # Planificateur et gestionnaire de jobs distribués
├── alerting_system.py     # Moteur de règles d'alerte et webhooks
├── file_transfer.py       # Transfert chiffré AES, SHA-256 et stockage partagé
├── service_discovery.py   # Découverte automatique mDNS / Zeroconf & Broadcast UDP
├── websocket_manager.py   # Gestionnaire des flux temps réel
├── health_checker.py      # Vérification de santé du cluster
├── nebulalab.py           # CLI d'administration du cluster
├── run_local.sh           # Script de lancement local rapide en 1 commande
├── install_agent.sh       # Script d'installation automatique pour nœuds distants
│
├── agent/                 # Module Agent : télémétrie par cœur et runner Docker
├── alerts/                # Module Alertes : notificateurs Webhook Discord/Slack/ntfy
├── api/                   # Module API : schémas Pydantic et validation
├── auth/                  # Module Auth : utilitaires de sécurité et signatures JWT
├── file_transfer/         # Module Fichiers : moteur de chiffrement et SFTP
├── monitoring/            # Monitoring : configuration Prometheus et alert_rules.yml
├── nginx/                 # Nginx : configuration de reverse proxy et WebSocket proxy
├── service_discovery/     # Réseau : listeners mDNS et broadcast UDP
│
├── dashboard/
│   ├── public/
│   │   ├── index.html     # Interface Web & Mobile PWA haute performance
│   │   └── manifest.json  # Configuration PWA pour smartphone
│   ├── src/app.js         # SDK client JavaScript / WebSocket
│   ├── styles/custom.css  # Styles cyber-dark et effets glassmorphism
│   ├── server.js          # Serveur Node.js (optionnel)
│   └── package.json
│
├── docker-compose.yml     # Déploiement multi-conteneurs pour the Master
├── docker-compose.agent.yml # Déploiement conteneurisé pour Nœuds distants
├── Dockerfile.api         # Image Docker du Master API
├── Dockerfile.agent       # Image Docker de l'Agent
└── requirements.txt       # Dépendances Python
```
---
## 🔒 Sécurité et Chiffrement

- **Communications & API** : Authentification Bearer JWT pour toutes les actions sensibles avec expiration paramétrable.
- **Stockage Cloud** : Chiffrement symétrique **Fernet AES-128** pour sécuriser les fichiers téléversés dans le stockage partagé.
- **Intégrité des Données** : Calcul automatique d'empreintes **SHA-256** pour valider chaque transfert inter-machines.
- **Réseau Local** : Clés de signature partagées pour authentifier les annonces de découverte UDP/mDNS.
