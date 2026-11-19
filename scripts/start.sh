#!/usr/bin/env bash
# Einrichten und Starten in einem Zug (Mac/Linux), fuer Teilnehmende:
#   curl -fsSL https://raw.githubusercontent.com/CHesseling/vfm-dokumenten-pipeline/main/scripts/start.sh | bash
# Voraussetzung: Docker (Docker Desktop oder colima) oder Podman (podman machine bzw.
# Linux) laeuft. Ollama fuer die lokalen Modelle; ohne Ollama geht es mit Cortecs
# (PROVIDER=cortecs in der .env, siehe README).
# Das Skript laedt das Projekt nach ~/vfm-pipeline, holt fehlende Ollama-Modelle,
# zieht das fertige App-Image und startet alles. Mehrfach ausfuehren ist ok (Update).
# Option --build: App-Image lokal bauen statt ziehen (dauert, braucht Internet):
#   curl -fsSL .../scripts/start.sh | bash -s -- --build
# Ueberschreibbar: VFM_ZIEL, VFM_ZIP_URL, VFM_IMAGE, VFM_PORT (Standard 8999, falls belegt),
# VFM_ENGINE (docker|podman, Standard: was laeuft, Docker zuerst).
set -euo pipefail

REPO="CHesseling/vfm-dokumenten-pipeline"
ZIEL="${VFM_ZIEL:-$HOME/vfm-pipeline}"
ZIP_URL="${VFM_ZIP_URL:-https://github.com/${REPO}/archive/refs/heads/main.zip}"
IMAGE="${VFM_IMAGE:-ghcr.io/chesseling/vfm-pipeline:latest}"
PORT="${VFM_PORT:-8999}"
GUI="http://localhost:${PORT}"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

BAUEN=0
for arg in "$@"; do
  case "$arg" in
    --build) BAUEN=1 ;;
    *) fehler "Unbekanntes Argument: '$arg' (erlaubt: --build)" ;;
  esac
done

# Container-Engine: Docker oder Podman, je nachdem was laeuft (VFM_ENGINE erzwingt eine)
CE=""
for e in ${VFM_ENGINE:-docker podman}; do
  if command -v "$e" > /dev/null && "$e" info > /dev/null 2>&1; then CE="$e"; break; fi
done

echo "==> Pruefe Voraussetzungen"
if [ -z "$CE" ]; then
  command -v docker > /dev/null || command -v podman > /dev/null \
    || fehler "Weder Docker noch Podman gefunden. Bitte Docker Desktop installieren: https://www.docker.com/products/docker-desktop/ (oder Podman: https://podman.io)"
  fehler "Docker/Podman laeuft nicht. Bitte Docker Desktop, colima bzw. 'podman machine start' starten und das Skript erneut ausfuehren."
fi
echo "  Container-Engine: $CE"
"$CE" compose version > /dev/null 2>&1 || fehler "'$CE compose' fehlt. Docker Desktop aktualisieren bzw. fuer Podman docker-compose oder podman-compose installieren."
# Ollama ist optional: ohne lokale Modelle geht es mit Cortecs (README "Ohne lokale Modelle")
OLLAMA_OK=0
if ! command -v ollama > /dev/null; then
  echo "  Ollama fehlt (https://ollama.com/download) - ohne lokale Modelle siehe README."
elif ! ollama list > /dev/null 2>&1; then
  echo "  Ollama laeuft nicht (Ollama-App starten) - ohne lokale Modelle siehe README."
else
  OLLAMA_OK=1
fi
command -v unzip > /dev/null || fehler "'unzip' fehlt."

echo "==> Lade Projekt nach $ZIEL"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL "$ZIP_URL" -o "$tmp/repo.zip" || fehler "Download fehlgeschlagen: $ZIP_URL"
unzip -q "$tmp/repo.zip" -d "$tmp/x"
quelle="$(find "$tmp/x" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -f "$quelle/docker-compose.yml" ] || fehler "Unerwarteter Inhalt im Download."
mkdir -p "$ZIEL"
# .env und material/ der Teilnehmenden bleiben erhalten
cp -R "$quelle/." "$ZIEL/"
mkdir -p "$ZIEL/material"

cd "$ZIEL"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  .env aus .env.example angelegt."
fi
env_setzen() {  # Schluessel in .env setzen oder anhaengen
  if grep -q "^$1=" .env; then
    sed -i.bak "s|^$1=.*|$1=$2|" .env && rm -f .env.bak
  else
    [ -z "$(tail -c 1 .env)" ] || echo >> .env  # letzte Zeile ohne Umbruch nicht verkleben
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
if [ "$BAUEN" = 1 ]; then
  env_setzen APP_IMAGE ""   # leer: compose nimmt das lokal gebaute vfm-pipeline:latest
else
  env_setzen APP_IMAGE "$IMAGE"
fi
env_setzen APP_PORT "$PORT"

if grep -qE '^PROVIDER=cortecs' .env; then
  echo "==> PROVIDER=cortecs in der .env: Ollama-Modelle werden nicht gebraucht"
elif [ "$OLLAMA_OK" = 0 ]; then
  echo "==> HINWEIS: Ohne Ollama melden chat, vision und embed in 'vfm check' Fehler."
  echo "    Entweder Ollama installieren/starten und das Skript erneut ausfuehren,"
  echo "    oder in $ZIEL/.env PROVIDER=cortecs und CORTECS_API_KEY eintragen (README)."
else
  echo "==> Pruefe Ollama-Modelle"
  vorhanden="$(ollama list | awk 'NR>1 {print $1}')"
  for modell in $(grep -E '^(CHAT|VISION|EMBED)_MODEL=' profile/ollama.env | cut -d= -f2 | sort -u); do
    if printf '%s\n' "$vorhanden" | grep -qxE "${modell}(:latest)?"; then
      echo "  $modell vorhanden"
    else
      echo "  lade $modell (mehrere GB, dauert) ..."
      ollama pull "$modell"
    fi
  done
fi

if [ "$BAUEN" = 1 ]; then
  echo "==> Lade Datenbank-Image"
  "$CE" compose pull db
  echo "==> Baue App-Image und starte (beim ersten Mal 10-20 Minuten)"
  "$CE" compose up -d --build
else
  echo "==> Lade Container-Images (beim ersten Mal mehrere GB)"
  "$CE" compose pull db app
  echo "==> Starte"
  "$CE" compose up -d --no-build
fi

echo "==> Warte auf die Oberflaeche"
for _ in $(seq 1 90); do
  if curl -fsS "$GUI/gesundheit" > /dev/null 2>&1; then
    echo
    echo "Fertig: $GUI"
    echo "Terminal-Befehle: cd \"$ZIEL\" && $CE compose exec app vfm check"
    echo "Terminal im Browser: http://localhost:7681 (Link \"Terminal\" in der Oberflaeche)"
    echo "Hinweis: In der Ollama-App die Kontextlaenge auf mindestens 16k stellen, sonst werden lange Dokumente abgeschnitten."
    if command -v open > /dev/null; then open "$GUI"; elif command -v xdg-open > /dev/null; then xdg-open "$GUI" > /dev/null 2>&1 || true; fi
    exit 0
  fi
  sleep 2
done
fehler "Die Oberflaeche antwortet nicht. Logs ansehen: cd \"$ZIEL\" && $CE compose logs app"
