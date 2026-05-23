#!/bin/bash
# Double-cliquer sur ce fichier pour lancer le site B.pc

cd "$(dirname "$0")"

echo "========================================"
echo "  B.pc — Démarrage du serveur..."
echo "========================================"
echo ""

# Utilise le venv du projet
PYTHON="./venv/bin/python3"
if [ ! -f "$PYTHON" ]; then
  PYTHON="python3"
fi

# Vérifie que les dépendances sont là
if ! $PYTHON -c "import uvicorn" 2>/dev/null; then
  echo "Installation des dépendances..."
  $PYTHON -m pip install uvicorn fastapi
fi

echo "✅ Serveur lancé !"
echo ""
echo "  → Ouvre ton navigateur sur : http://localhost:8000"
echo ""
echo "  (Garde cette fenêtre ouverte tant que tu utilises le site)"
echo "  (Ferme-la ou appuie sur CTRL+C pour arrêter)"
echo ""
echo "========================================"
echo ""

# Ouvre automatiquement le navigateur après 2 secondes
sleep 2 && open "http://localhost:8000" &

# Libère le port 8000 si déjà occupé (évite "address already in use")
EXISTING=$(lsof -ti:8000 2>/dev/null)
if [ -n "$EXISTING" ]; then
  echo "  ↪ Port 8000 déjà utilisé — arrêt de l'ancien processus..."
  kill -9 $EXISTING 2>/dev/null
  sleep 1
fi

# Lance le serveur avec le venv
$PYTHON -m uvicorn api.main:app --host 0.0.0.0 --port 8000
