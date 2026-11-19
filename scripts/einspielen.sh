#!/usr/bin/env bash
# Spielt das Offline-Paket (USB-Stick) auf diesem Rechner ein.
# Aufruf (im Stick-Ordner): ./einspielen.sh [ZIELVERZEICHNIS]   (Standard: ~/vfm-pipeline)
set -euo pipefail

STICK="$(cd "$(dirname "$0")" && pwd -P)"
ZIEL="${1:-$HOME/vfm-pipeline}"

# Ziel aufloesen (naechster vorhandener Elternordner, Symlinks aufgeloest) und
# VOR dem Anlegen pruefen, dass es nicht auf dem Stick liegt (exFAT, geht beim Abziehen verloren)
rest=""
basis="$ZIEL"
while [ ! -d "$basis" ]; do
  rest="/$(basename "$basis")$rest"
  basis="$(dirname "$basis")"
done
ZIEL="$(cd "$basis" && pwd -P)$rest"
case "$ZIEL/" in
  "$STICK"/*)
    echo "Das Ziel liegt auf dem Stick ($ZIEL). Bitte ein Verzeichnis auf dem Rechner waehlen." >&2
    exit 1 ;;
esac
mkdir -p "$ZIEL"

case "$(uname -m)" in
  arm64|aarch64) ARCH=arm64 ;;
  x86_64|amd64) ARCH=amd64 ;;
  *) echo "Unbekannte Architektur: $(uname -m)" >&2; exit 1 ;;
esac
echo "Architektur: $ARCH"

# Container-Engine: Docker oder Podman, je nachdem was laeuft (VFM_ENGINE erzwingt eine)
CE=""
for e in ${VFM_ENGINE:-docker podman}; do
  if command -v "$e" > /dev/null && "$e" info > /dev/null 2>&1; then CE="$e"; break; fi
done
[ -n "$CE" ] || {
  echo "Weder Docker noch Podman laeuft - bitte Docker Desktop, colima bzw. 'podman machine start' starten und das Skript erneut ausführen." >&2
  exit 1
}
echo "Container-Engine: $CE"

laden() {
  local datei="$STICK/images/$1"
  if [ ! -f "$datei" ]; then
    echo "  uebersprungen (nicht auf dem Stick): $1"
    return 0
  fi
  echo "  lade $1 ..."
  gunzip -c "$datei" | "$CE" load
}

echo "==> Container-Images laden"
if [ ! -f "$STICK/images/vfm-pipeline-${ARCH}.tar.gz" ]; then
  echo "App-Image für $ARCH fehlt auf dem Stick" >&2
  exit 1
fi
laden "vfm-pipeline-${ARCH}.tar.gz"
"$CE" tag "vfm-pipeline:latest-${ARCH}" vfm-pipeline:latest
laden "pgvector-pg16-${ARCH}.tar.gz"

read -r -p "Ollama-Image (fuer Ollama im Container) auch laden? [j/N] " antwort || antwort=""
case "$antwort" in
  j|J|y|Y) laden "ollama-${ARCH}.tar.gz" ;;
esac

if [ -d "$STICK/ollama-modelle" ]; then
  MODELLE="${OLLAMA_MODELS:-$HOME/.ollama/models}"
  read -r -p "Ollama-Modelle nach $MODELLE kopieren (vorhandene Dateien bleiben erhalten)? [j/N] " antwort || antwort=""
  case "$antwort" in
    j|J|y|Y)
      mkdir -p "$MODELLE"
      cp -Rn "$STICK/ollama-modelle/." "$MODELLE/" || true
      echo "  Modelle kopiert (vorhandene Dateien wurden nicht ueberschrieben)."
      ;;
    *) echo "  Modelle uebersprungen." ;;
  esac
else
  echo "Keine Ollama-Modelle auf dem Stick."
fi

echo "==> Projekt entpacken nach $ZIEL"
entpacken=1
if [ -n "$(ls -A "$ZIEL")" ]; then
  read -r -p "$ZIEL ist nicht leer. Vorhandene Projektdateien ueberschreiben? [j/N] " antwort || antwort=""
  case "$antwort" in
    j|J|y|Y) ;;
    *) entpacken=0; echo "  Entpacken uebersprungen." ;;
  esac
fi
if [ "$entpacken" = 1 ]; then
  tar -xzf "$STICK/vfm-pipeline-repo.tar.gz" -C "$ZIEL" --strip-components=1
fi
if [ ! -f "$ZIEL/.env" ]; then
  cp "$ZIEL/.env.example" "$ZIEL/.env"
  echo "  .env aus .env.example angelegt."
else
  echo "  .env existiert bereits, unveraendert. Bitte mit .env.example auf neue Schluessel vergleichen."
fi

echo
echo "Fertig. Weiter mit:"
echo "  cd \"$ZIEL\" && $CE compose up -d && $CE compose exec app vfm check"
