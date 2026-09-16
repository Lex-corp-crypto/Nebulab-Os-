#!/usr/bin/env bash
# ==============================================================================
# NebulaLab OS - Quick Local Launcher & Supervisor with Zero-Config Remote Tunnel
# Lance et maintient le Master API, l'Agent et le Tunnel d'accès distant en arrière-plan.
# Supporte : start, stop, restart, status, logs, tunnel, foreground (-f)
# ==============================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

mkdir -p "$DIR/data/shared_storage"

PID_API="$DIR/data/master_api.pid"
PID_AGENT="$DIR/data/agent_local.pid"
LOG_API="$DIR/data/master_api.log"
LOG_AGENT="$DIR/data/agent_local.log"
LOG_TUNNEL="$DIR/data/tunnel.log"
URL_TUNNEL_FILE="$DIR/data/tunnel_url.txt"

# Chargement du fichier .env si présent
if [ -f "$DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$DIR/.env" 2>/dev/null || true
    set +a
fi

# Détection et activation du Python dans .venv
PYTHON_BIN="$DIR/.venv/bin/python"

ensure_environment() {
    if [ ! -f "$PYTHON_BIN" ]; then
        echo "📦 Création de l'environnement virtuel Python (.venv)..."
        python3 -m venv "$DIR/.venv"
        "$DIR/.venv/bin/pip" install --upgrade pip >/dev/null 2>&1 || true
        echo "📥 Installation des dépendances depuis requirements.txt..."
        "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
    fi
}

get_local_ip() {
    # Détection fiable de l'IP IPv4 LAN
    local ip
    ip=$("$PYTHON_BIN" -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
    s.close()
except Exception:
    print('127.0.0.1')
" 2>/dev/null)
    if [ -z "$ip" ]; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    echo "${ip:-localhost}"
}

get_tunnel_url() {
    if [ -f "$URL_TUNNEL_FILE" ]; then
        cat "$URL_TUNNEL_FILE" 2>/dev/null || true
    fi
}

is_running() {
    local pid_file="$1"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

is_tunnel_running() {
    local t_url
    t_url=$(get_tunnel_url)
    if [ -n "$t_url" ]; then
        return 0
    fi
    return 1
}

stop_services() {
    echo "🛑 Arrêt des services NebulaLab..."
    
    # 1. Arrêter l'agent
    if is_running "$PID_AGENT"; then
        local apid
        apid=$(cat "$PID_AGENT")
        echo "  Arrêt de l'Agent local (PID: $apid)..."
        kill -15 "$apid" 2>/dev/null || true
        sleep 1
        kill -9 "$apid" 2>/dev/null || true
        rm -f "$PID_AGENT"
    fi

    # 2. Arrêter l'API Master
    if is_running "$PID_API"; then
        local mpid
        mpid=$(cat "$PID_API")
        echo "  Arrêt du Master API (PID: $mpid)..."
        kill -15 "$mpid" 2>/dev/null || true
        sleep 1
        kill -9 "$mpid" 2>/dev/null || true
        rm -f "$PID_API"
    fi

    # 3. Arrêter d'éventuels processus tunnel
    "$PYTHON_BIN" "$DIR/tunnel_manager.py" stop >/dev/null 2>&1 || true
    rm -f "$URL_TUNNEL_FILE"

    # 4. Nettoyage de sécurité des processus orphelins
    pkill -f "python.*main_api.py" 2>/dev/null || true
    pkill -f "python.*agent_service.py" 2>/dev/null || true
    rm -f "$PID_API" "$PID_AGENT"
    echo "✅ Tous les services sont arrêtés."
}

show_banner() {
    local local_ip
    local_ip=$(get_local_ip)
    local public_url
    public_url=$(get_tunnel_url)
    
    echo ""
    echo "=================================================================="
    echo "  🎉 NebulaLab OS est OPÉRATIONNEL & ACTIF EN ARRIÈRE-PLAN !"
    echo "=================================================================="
    echo "  💻 Interface Web Local  : http://localhost:8000"
    echo "  📱 Accès Réseau Wi-Fi   : http://${local_ip}:8000"
    if [ -n "$public_url" ]; then
        echo "  🌐 Accès Distant Sécurisé: ${public_url} (Zéro-Config !)"
        echo "  ⚡ Commande 1-Clic Nœud : curl -sSL ${public_url}/join | bash"
    else
        echo "  🌐 Accès Distant Sécurisé: En cours de négociation..."
        echo "  ⚡ Commande 1-Clic Nœud : curl -sSL http://${local_ip}:8000/join | bash"
    fi
    echo "  📖 Documentation OpenAPI: http://localhost:8000/docs"
    echo "  📊 Métriques Prometheus : http://localhost:8000/metrics"
    echo "  🩺 Vérification Santé   : http://localhost:8000/health"
    echo "=================================================================="
    echo ""
    echo "🛠️ Commandes utiles pour gérer le cluster :"
    echo "  ./run_local.sh status    -> Vérifier l'état et l'accès aux interfaces"
    echo "  ./run_local.sh logs      -> Voir les logs en direct (Ctrl+C pour quitter)"
    echo "  ./run_local.sh tunnel    -> Afficher l'URL du tunnel distant"
    echo "  ./run_local.sh restart   -> Redémarrer le Master, l'Agent et le Tunnel"
    echo "  ./run_local.sh stop      -> Arrêter le cluster proprement"
    echo "  ./nebulalab.py status    -> Afficher l'état du cluster via la CLI"
    echo ""
}

start_services() {
    ensure_environment

    echo "🌌 Initialisation de NebulaLab OS..."

    # Arrêter d'éventuelles instances précédentes
    if is_running "$PID_API" || is_running "$PID_AGENT"; then
        echo "⚠️  Des processus NebulaLab sont déjà en cours d'exécution. Redémarrage propre..."
        stop_services
        sleep 1
    else
        # Sécurité supplémentaire
        pkill -f "python.*main_api.py" 2>/dev/null || true
        pkill -f "python.*agent_service.py" 2>/dev/null || true
    fi

    # 1. Démarrer le Master API en arrière-plan totalement détaché (setsid + disown)
    echo "🚀 Démarrage du Master API sur http://0.0.0.0:8000 ..."
    setsid "$PYTHON_BIN" "$DIR/main_api.py" < /dev/null > "$LOG_API" 2>&1 &
    MASTER_PID=$!
    disown "$MASTER_PID" 2>/dev/null || true
    echo "$MASTER_PID" > "$PID_API"

    # 2. Attendre que l'API réponde
    echo "⏳ Attente de la disponibilité de l'API..."
    API_READY=0
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        if curl -s http://localhost:8000/health >/dev/null 2>&1; then
            API_READY=1
            break
        fi
        sleep 1
    done

    if [ "$API_READY" -ne 1 ]; then
        echo "❌ Erreur: Master API n'a pas pu démarrer."
        echo "Dernières lignes de $LOG_API :"
        echo "--------------------------------------------------"
        tail -n 20 "$LOG_API" 2>/dev/null || true
        echo "--------------------------------------------------"
        stop_services
        exit 1
    fi
    echo "✅ Master API prêt !"

    # 3. Démarrer l'Agent local
    echo "⚡ Démarrage de l'Agent Local..."
    setsid env HOSTNAME="$(hostname)" API_URL="http://localhost:8000" "$PYTHON_BIN" "$DIR/agent_service.py" < /dev/null > "$LOG_AGENT" 2>&1 &
    AGENT_PID=$!
    disown "$AGENT_PID" 2>/dev/null || true
    echo "$AGENT_PID" > "$PID_AGENT"

    sleep 2
    if ! kill -0 "$AGENT_PID" 2>/dev/null; then
        echo "⚠️  Attention: L'Agent local s'est arrêté de façon inattendue. Vérification des logs :"
        tail -n 20 "$LOG_AGENT" 2>/dev/null || true
    else
        echo "✅ Agent Local actif (PID: $AGENT_PID) !"
    fi

    # Attendre quelques secondes que le tunnel s'établisse pour l'afficher
    sleep 2
    show_banner
}

run_foreground() {
    ensure_environment
    start_services

    echo "👀 Mode surveillance actif (Appuyez sur Ctrl+C pour arrêter)..."
    
    cleanup() {
        echo ""
        stop_services
        exit 0
    }
    trap cleanup SIGINT SIGTERM SIGHUP

    # Boucle de supervision active
    while true; do
        if ! is_running "$PID_API"; then
            echo "❌ Le Master API s'est arrêté de manière inattendue !"
            tail -n 15 "$LOG_API" 2>/dev/null || true
            break
        fi
        if ! is_running "$PID_AGENT"; then
            echo "⚠️ L'Agent Local s'est arrêté. Tentative de redémarrage..."
            nohup env HOSTNAME="$(hostname)" API_URL="http://localhost:8000" "$PYTHON_BIN" "$DIR/agent_service.py" > "$LOG_AGENT" 2>&1 &
            echo $! > "$PID_AGENT"
        fi
        sleep 3
    done
}

status_services() {
    local local_ip
    local_ip=$(get_local_ip)
    local public_url
    public_url=$(get_tunnel_url)
    local version=""
    if [ -f "$DIR/VERSION" ]; then
        version=$(cat "$DIR/VERSION")
    fi

    echo "=================================================================="
    echo "  📊 État des services NebulaLab OS"
    if [ -n "$version" ]; then
        echo "  🏷️  Version: $version"
    fi
    echo "=================================================================="

    local api_ok=0
    local agent_ok=0

    if is_running "$PID_API"; then
        local mpid
        mpid=$(cat "$PID_API")
        echo "  🟢 Master API    : EN LIGNE (PID: $mpid) sur http://0.0.0.0:8000"
        api_ok=1
    else
        echo "  🔴 Master API    : HORS-LIGNE"
    fi

    if is_running "$PID_AGENT"; then
        local apid
        apid=$(cat "$PID_AGENT")
        echo "  🟢 Agent Local   : EN LIGNE (PID: $apid)"
        agent_ok=1
    else
        echo "  🔴 Agent Local   : HORS-LIGNE"
    fi

    if [ -n "$public_url" ]; then
        echo "  🟢 Tunnel Distant: ACTIF & CONNECTÉ -> ${public_url}"
    else
        echo "  ⚪ Tunnel Distant: Non connecté ou local uniquement"
    fi

    echo "------------------------------------------------------------------"
    if [ "$api_ok" -eq 1 ]; then
        if curl -s http://localhost:8000/health >/dev/null 2>&1; then
            echo "  🩺 Endpoint /health : 200 OK (Répond correctement)"
            echo "  💻 Dashboard PC     : http://localhost:8000"
            echo "  📱 Accès Wi-Fi      : http://${local_ip}:8000"
            if [ -n "$public_url" ]; then
                echo "  🌐 Accès Partout (4G/5G/Extérieur): ${public_url}"
                echo "  ⚡ Commande 1-Clic Nœud Distant    : curl -sSL ${public_url}/join | bash"
            else
                echo "  ⚡ Commande 1-Clic Nœud Local      : curl -sSL http://${local_ip}:8000/join | bash"
            fi
            echo "  📖 Docs API         : http://localhost:8000/docs"
        else
            echo "  ⚠️ Le processus API tourne mais ne répond pas encore aux requêtes HTTP."
        fi
    else
        echo "  ℹ️  Pour démarrer : ./run_local.sh start"
    fi
    echo "=================================================================="
}

show_logs() {
    local target="${1:-all}"
    if [ "$target" = "api" ]; then
        echo "📜 Affichage des logs Master API ($LOG_API) :"
        tail -f -n 50 "$LOG_API"
    elif [ "$target" = "agent" ]; then
        echo "📜 Affichage des logs Agent ($LOG_AGENT) :"
        tail -f -n 50 "$LOG_AGENT"
    elif [ "$target" = "tunnel" ]; then
        echo "📜 Affichage des logs Tunnel Distant ($LOG_TUNNEL) :"
        tail -f -n 50 "$LOG_TUNNEL"
    else
        echo "📜 Affichage combiné des logs (Master API & Agent) :"
        tail -f -n 25 "$LOG_API" "$LOG_AGENT"
    fi
}

show_tunnel() {
    local public_url
    public_url=$(get_tunnel_url)
    if [ -n "$public_url" ]; then
        echo "🌐 URL Publique Active : $public_url"
    else
        echo "⚠️  Aucun tunnel distant actif pour l'instant."
    fi
}

# Routage des commandes
CMD="${1:-start}"

case "$CMD" in
    start)
        start_services
        ;;
    foreground|-f|--foreground)
        run_foreground
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        sleep 1
        start_services
        ;;
    status)
        status_services
        ;;
    logs)
        show_logs "$2"
        ;;
    tunnel)
        show_tunnel
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|tunnel|foreground}"
        echo ""
        echo "Options:"
        echo "  start                : Démarre Master API, Agent et Tunnel en arrière-plan"
        echo "  foreground           : Démarre avec supervision interactive en avant-plan (-f)"
        echo "  stop                 : Arrête tous les services proprement"
        echo "  restart              : Redémarre l'API, l'Agent et le Tunnel"
        echo "  status               : Affiche l'état des services et les URLs des interfaces"
        echo "  tunnel               : Affiche l'URL du tunnel distant actif"
        echo "  logs [all|api|agent|tunnel] : Affiche les logs en direct"
        exit 1
        ;;
esac
