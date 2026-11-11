#!/usr/bin/env bash
# Baut das Offline-Paket fuer den USB-Stick.
# Aufruf:
#   scripts/usb_paket_bauen.sh ZIEL [--ohne-ollama-modelle]
#   scripts/usb_paket_bauen.sh --nur-modelle-pruefen     (Trockenlauf: listet
#                                                         die Modell-Dateien, kopiert nichts)
# Voraussetzung: dist/vfm-pipeline-amd64.tar.gz und -arm64.tar.gz existieren
# (scripts/image_bauen.sh), Docker laeuft, Internet fuer die Fremd-Images.
set -euo pipefail

AUFRUF_VERZEICHNIS="$PWD"
cd "$(dirname "$0")/.."
REPO="$PWD"

ZIEL=""
OHNE_MODELLE=0
NUR_PRUEFEN=0
for arg in "$@"; do
  case "$arg" in
    --ohne-ollama-modelle) OHNE_MODELLE=1 ;;
    --nur-modelle-pruefen) NUR_PRUEFEN=1 ;;
    -*) echo "Unbekannte Option: $arg" >&2; exit 2 ;;
    *) ZIEL="$arg" ;;
  esac
done
if [ "$NUR_PRUEFEN" = 0 ] && [ -z "$ZIEL" ]; then
  echo "Aufruf: $0 ZIEL [--ohne-ollama-modelle] | --nur-modelle-pruefen" >&2
  exit 2
fi

# ZIEL relativ zum Aufrufer (nicht zum Repo-Root) aufloesen
if [ -n "$ZIEL" ]; then
  case "$ZIEL" in
    /*) ;;
    *) ZIEL="$AUFRUF_VERZEICHNIS/$ZIEL" ;;
  esac
fi

OLLAMA_HOME="${OLLAMA_MODELS:-$HOME/.ollama/models}"

# ---------------------------------------------------------------- Modelle

modellnamen() {
  # Liest CHAT_MODEL, VISION_MODEL, EMBED_MODEL aus profile/ollama.env
  local schluessel
  for schluessel in CHAT_MODEL VISION_MODEL EMBED_MODEL; do
    sed -n "s/^${schluessel}=//p" profile/ollama.env | head -n1
  done
}

manifest_pfad() {
  # "qwen3.5:4b" -> manifests/registry.ollama.ai/library/qwen3.5/4b
  local name="$1" tag="latest" pfad
  if [[ "$name" == *:* ]]; then tag="${name##*:}"; name="${name%%:*}"; fi
  if [[ "$name" == */* ]]; then pfad="$name"; else pfad="library/$name"; fi
  echo "manifests/registry.ollama.ai/${pfad}/${tag}"
}

modell_dateien() {
  # Gibt relative Pfade (unter OLLAMA_HOME) aus: Manifeste + referenzierte Blobs
  local name rel digest
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    rel="$(manifest_pfad "$name")"
    if [ ! -f "$OLLAMA_HOME/$rel" ]; then
      echo "FEHLER: Manifest fuer '$name' fehlt: $OLLAMA_HOME/$rel (ollama pull $name)" >&2
      return 1
    fi
    echo "$rel"
    python3 -I -c '
import json, sys
m = json.load(open(sys.argv[1]))
for e in [m["config"]] + m["layers"]:
    print("blobs/" + e["digest"].replace(":", "-"))
' "$OLLAMA_HOME/$rel" || return 1
  done < <(modellnamen) | sort -u
}

modelle_pruefen() {
  local rel gesamt=0 groesse dateien
  dateien="$(modell_dateien)"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    if [ ! -f "$OLLAMA_HOME/$rel" ]; then
      echo "FEHLER: Blob fehlt: $OLLAMA_HOME/$rel" >&2
      return 1
    fi
    groesse="$(wc -c < "$OLLAMA_HOME/$rel" | tr -d ' ')"
    gesamt=$((gesamt + groesse))
    printf '%14d  %s\n' "$groesse" "$rel"
  done <<< "$dateien"
  echo "Summe: $gesamt Bytes ($((gesamt / 1024 / 1024)) MiB)"
}

if [ "$NUR_PRUEFEN" = 1 ]; then
  echo "Modelle laut profile/ollama.env: $(modellnamen | tr '\n' ' ')"
  modelle_pruefen
  exit 0
fi

docker info > /dev/null 2>&1 || {
  echo "Docker läuft nicht – bitte Docker Desktop bzw. colima starten und das Skript erneut ausführen." >&2
  exit 1
}

# ----------------------------------------------------------- Fremd-Images

case "$(uname -m)" in
  arm64|aarch64) NATIV=arm64 ;;
  *) NATIV=amd64 ;;
esac

pull_arch() {
  # pull_arch IMAGE ARCH: zieht das Image in der Ziel-Architektur und prueft sie.
  # Der Cache ignoriert --platform manchmal -> bei Abweichung per Digest ziehen.
  local image="$1" arch="$2" gefunden digest
  docker pull --platform "linux/${arch}" "$image" > /dev/null
  gefunden="$(docker image inspect "$image" --format '{{.Architecture}}')"
  if [ "$gefunden" != "$arch" ]; then
    echo "  Architektur '$gefunden' statt '$arch' - ziehe per Digest" >&2
    digest="$(docker buildx imagetools inspect "$image" --raw | python3 -I -c '
import json, sys
arch = sys.argv[1]
idx = json.load(sys.stdin)
for m in idx["manifests"]:
    p = m.get("platform", {})
    if p.get("os") == "linux" and p.get("architecture") == arch:
        print(m["digest"]); break
' "$arch")"
    [ -n "$digest" ] || { echo "FEHLER: kein Digest fuer $image/$arch" >&2; return 1; }
    docker rmi -f "$image" > /dev/null
    docker pull "${image%%:*}@${digest}" > /dev/null
    docker tag "${image%%:*}@${digest}" "$image"
    gefunden="$(docker image inspect "$image" --format '{{.Architecture}}')"
  fi
  if [ "$gefunden" != "$arch" ]; then
    echo "FEHLER: $image hat Architektur '$gefunden', erwartet '$arch'." >&2
    return 1
  fi
}

abbild_sichern() {
  # abbild_sichern IMAGE ARCH DATEI
  echo "==> $1 (${2}) -> $3"
  pull_arch "$1" "$2"
  docker save --platform "linux/${2}" "$1" | gzip > "$3"
}

# ------------------------------------------------------------------ Paket

for arch in amd64 arm64; do
  [ -f "dist/vfm-pipeline-${arch}.tar.gz" ] || {
    echo "FEHLER: dist/vfm-pipeline-${arch}.tar.gz fehlt (scripts/image_bauen.sh ${arch})" >&2
    exit 1
  }
done

mkdir -p "$ZIEL/images"
ZIEL="$(cd "$ZIEL" && pwd)"

echo "==> App-Images kopieren"
for arch in amd64 arm64; do
  cp "dist/vfm-pipeline-${arch}.tar.gz" "$ZIEL/images/"
done

for arch in amd64 arm64; do
  abbild_sichern pgvector/pgvector:pg16 "$arch" "$ZIEL/images/pgvector-pg16-${arch}.tar.gz"
  abbild_sichern ollama/ollama:latest "$arch" "$ZIEL/images/ollama-${arch}.tar.gz"
done
# Lokale Dev-Umgebung wieder auf die native Architektur zuruecksetzen
echo "==> Native Architektur (${NATIV}) wiederherstellen"
pull_arch pgvector/pgvector:pg16 "$NATIV"
pull_arch ollama/ollama:latest "$NATIV"

if [ "$OHNE_MODELLE" = 0 ]; then
  echo "==> Ollama-Modelle kopieren"
  dateien="$(modell_dateien)"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    mkdir -p "$ZIEL/ollama-modelle/$(dirname "$rel")"
    cp "$OLLAMA_HOME/$rel" "$ZIEL/ollama-modelle/$rel"
  done <<< "$dateien"
else
  echo "==> Ollama-Modelle uebersprungen (--ohne-ollama-modelle)"
fi

echo "==> Repo-Snapshot (git archive HEAD)"
git archive --format=tar.gz --prefix=vfm-pipeline/ -o "$ZIEL/vfm-pipeline-repo.tar.gz" HEAD

echo "==> Einspiel-Skripte und Anleitung"
cp scripts/einspielen.sh scripts/einspielen.ps1 "$ZIEL/"
chmod +x "$ZIEL/einspielen.sh"

cat > "$ZIEL/ANLEITUNG.md" <<'ANLEITUNG'
# Workshop-Pipeline: Offline-Paket

Dieser Stick enthaelt alles, um die Pipeline ohne Internet zu starten.

## Inhalt

- `images/` Docker-Images fuer amd64 (Intel/Windows/Linux-Server) und arm64
  (Apple Silicon): App, Datenbank (pgvector), Ollama
- `ollama-modelle/` Sprachmodelle (qwen3.5:4b, qwen3-vl:8b, bge-m3) im
  Ollama-Format (fehlt, wenn der Stick ohne Modelle gebaut wurde)
- `vfm-pipeline-repo.tar.gz` Projektordner mit Code, Profilen, `.env.example`
- `einspielen.sh` (Mac/Linux), `einspielen.ps1` (Windows)

## Voraussetzungen

- Der Stick muss mit **exFAT** formatiert sein (FAT32 kann keine Dateien
  > 4 GB speichern, die Image-Dateien sind ~3 GB gross, Gesamtgroesse > 10 GB).

- Docker (Docker Desktop bzw. Docker Engine mit `docker compose`) ist
  installiert und laeuft.
- Fuer die lokalen Modelle: Ollama (https://ollama.com) ist auf dem
  Rechner installiert, oder du nutzt das mitgelieferte Ollama-Image
  (Variante B unten).
- In der Ollama-App die Kontextlaenge auf mindestens 16k stellen (oder Ollama
  mit OLLAMA_CONTEXT_LENGTH=16384 starten), sonst schneidet Ollama lange
  Dokumente still ab. Variante B setzt das bereits.

## Einspielen

Mac / Linux (Terminal, im Stick-Ordner):

    ./einspielen.sh                 # entpackt nach ~/vfm-pipeline
    ./einspielen.sh ~/vfm           # oder in einen anderen Ordner

Standardziel ist `~/vfm-pipeline` (nicht der Stick). Ist der Stick ohne
Ausfuehrrecht eingebunden (noexec), starte stattdessen: `bash einspielen.sh`.

Windows (PowerShell, im Stick-Ordner):

    powershell -ExecutionPolicy Bypass -File .\einspielen.ps1
    powershell -ExecutionPolicy Bypass -File .\einspielen.ps1 -Ziel C:\vfm

Standardziel ist `%USERPROFILE%\vfm-pipeline`.

Das Skript erkennt die Architektur, laedt die passenden Images
(`docker load`), fragt, ob die Modelle nach `~/.ollama/models` kopiert
werden sollen (vorhandene Dateien bleiben erhalten), entpackt das Projekt und legt `.env` aus `.env.example` an.

## Starten

    cd vfm-pipeline
    docker compose up -d
    docker compose exec app vfm check      # alle Pruefungen sollten gruen sein

Die Oberflaeche laeuft unter http://localhost:8999. Weitere Schritte
(Material einlesen, Suche, Auswertung) stehen in der `README.md` im
Projektordner.

## Variante B: Ollama im Container statt auf dem Rechner

    docker compose --profile ollama up -d
    docker compose --profile ollama run --rm --no-deps \
      -v "<Stick>/ollama-modelle:/src:ro" --entrypoint sh ollama \
      -c "mkdir -p /root/.ollama/models && cp -r /src/. /root/.ollama/models/"

Danach in `.env` die Ollama-Adressen auf `http://ollama:11434/v1` setzen.
ANLEITUNG

echo "==> Fertig: $ZIEL"
du -sh "$ZIEL"
