#!/usr/bin/env bash
# ==============================================================================
# NebulaLab OS - 1-Line Agent Installer for any Linux node or Android (Termux)
# ==============================================================================
set -e

MASTER_URL="${1:-${API_URL:-}}"

echo "=================================================================="
echo "  🌌 Installation de l'Agent NebulaLab OS..."
echo "=================================================================="

# Détection de l'environnement
if [ -n "$ANDROID_ROOT" ] || [ -d "/data/data/com.termux" ]; then
    echo "📱 Détection : Android (Termux)"
    pkg update -y 2>/dev/null || true
    pkg install -y python python-pip git curl 2>/dev/null || true
else
    echo "💻 Détection : Linux Standard (Pop!_OS / Ubuntu / Debian / Fedora)"
    if command -v apt-get >/dev/null 2>&1; then
        (sudo apt-get update -y && sudo apt-get install -y python3 python3-pip python3-venv curl) 2>/dev/null || true
    fi
fi

# Création du dossier agent
INSTALL_DIR="$HOME/.nebulalab_agent"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    python3 -m venv "$INSTALL_DIR/.venv" 2>/dev/null || python -m venv "$INSTALL_DIR/.venv" 2>/dev/null || true
fi

PYTHON_BIN="$INSTALL_DIR/.venv/bin/python"
PIP_BIN="$INSTALL_DIR/.venv/bin/pip"

if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
    PIP_BIN="pip3"
fi

"$PIP_BIN" install --upgrade pip >/dev/null 2>&1 || true
"$PIP_BIN" install psutil aiohttp zeroconf cryptography requests

# Télécharger ou copier les fichiers nécessaires
if [ -n "$MASTER_URL" ]; then
    echo "📥 Téléchargement des modules depuis $MASTER_URL..."
    curl -sSL -k "$MASTER_URL/static/agent_service.py" -o "$INSTALL_DIR/agent_service.py" 2>/dev/null || true
    curl -sSL -k "$MASTER_URL/static/service_discovery.py" -o "$INSTALL_DIR/service_discovery.py" 2>/dev/null || true
    curl -sSL -k "$MASTER_URL/static/file_transfer.py" -o "$INSTALL_DIR/file_transfer.py" 2>/dev/null || true
elif [ -f "./agent_service.py" ]; then
    echo "📋 Copie des modules locaux..."
    cp -f ./agent_service.py "$INSTALL_DIR/"
    cp -f ./service_discovery.py "$INSTALL_DIR/"
    cp -f ./file_transfer.py "$INSTALL_DIR/" 2>/dev/null || true
else
    echo "🔍 Recherche du master local sur http://localhost:8000..."
    curl -sSL -k "http://localhost:8000/static/agent_service.py" -o "$INSTALL_DIR/agent_service.py" 2>/dev/null || true
    curl -sSL -k "http://localhost:8000/static/service_discovery.py" -o "$INSTALL_DIR/service_discovery.py" 2>/dev/null || true
    curl -sSL -k "http://localhost:8000/static/file_transfer.py" -o "$INSTALL_DIR/file_transfer.py" 2>/dev/null || true
fi

echo "🚀 Lancement de l'agent NebulaLab..."
export API_URL="$MASTER_URL"
export HOSTNAME="$(hostname)"

exec "$PYTHON_BIN" "$INSTALL_DIR/agent_service.py"

