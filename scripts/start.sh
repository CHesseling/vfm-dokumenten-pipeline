#!/usr/bin/env bash
# Einrichten und Starten in einem Zug (Mac/Linux), fuer Teilnehmende:
#   curl -fsSL https://raw.githubusercontent.com/CHesseling/vfm-dokumenten-pipeline/main/scripts/start.sh | bash
# Voraussetzung: Docker (Docker Desktop oder colima) und Ollama sind installiert und laufen.
# Das Skript laedt das Projekt nach ~/vfm-pipeline, holt fehlende Ollama-Modelle,
# zieht das fertige App-Image und startet alles. Mehrfach ausfuehren ist ok (Update).
# Ueberschreibbar: VFM_ZIEL, VFM_ZIP_URL, VFM_IMAGE, VFM_PORT (Standard 8999, falls belegt).
set -euo pipefail

REPO="CHesseling/vfm-dokumenten-pipeline"
ZIEL="${VFM_ZIEL:-$HOME/vfm-pipeline}"
ZIP_URL="${VFM_ZIP_URL:-https://github.com/${REPO}/archive/refs/heads/main.zip}"
IMAGE="${VFM_IMAGE:-ghcr.io/chesseling/vfm-pipeline:latest}"
PORT="${VFM_PORT:-8999}"
GUI="http://localhost:${PORT}"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

echo "==> Pruefe Voraussetzungen"
command -v docker > /dev/null || fehler "Docker fehlt. Bitte Docker Desktop installieren: https://www.docker.com/products/docker-desktop/"
docker info > /dev/null 2>&1 || fehler "Docker laeuft nicht. Bitte Docker Desktop (bzw. colima) starten und das Skript erneut ausfuehren."
docker compose version > /dev/null 2>&1 || fehler "'docker compose' fehlt. Bitte Docker Desktop aktualisieren."
command -v ollama > /dev/null || fehler "Ollama fehlt. Bitte installieren: https://ollama.com/download"
ollama list > /dev/null 2>&1 || fehler "Ollama laeuft nicht. Bitte die Ollama-App starten und das Skript erneut ausfuehren."
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
env_setzen APP_IMAGE "$IMAGE"
env_setzen APP_PORT "$PORT"

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

echo "==> Lade Docker-Images (beim ersten Mal mehrere GB)"
docker compose pull db app
echo "==> Starte"
docker compose up -d --no-build

echo "==> Warte auf die Oberflaeche"
for _ in $(seq 1 90); do
  if curl -fsS "$GUI/gesundheit" > /dev/null 2>&1; then
    echo
    echo "Fertig: $GUI"
    echo "Terminal-Befehle: cd \"$ZIEL\" && docker compose exec app vfm check"
    echo "Hinweis: In der Ollama-App die Kontextlaenge auf mindestens 16k stellen, sonst werden lange Dokumente abgeschnitten."
    if command -v open > /dev/null; then open "$GUI"; elif command -v xdg-open > /dev/null; then xdg-open "$GUI" > /dev/null 2>&1 || true; fi
    exit 0
  fi
  sleep 2
done
fehler "Die Oberflaeche antwortet nicht. Logs ansehen: cd \"$ZIEL\" && docker compose logs app"
