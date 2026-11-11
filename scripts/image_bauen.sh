#!/usr/bin/env bash
# Baut das App-Image fuer eine Architektur und exportiert es nach dist/.
# Aufruf: scripts/image_bauen.sh amd64|arm64
# Ergebnis: vfm-pipeline:latest-<arch> (lokal), dist/vfm-pipeline-<arch>.tar.gz.
# "vfm-pipeline:latest" wird nur gesetzt, wenn <arch> der Host-Architektur
# entspricht (sonst liefe die lokale Entwicklung unter Emulation).
set -euo pipefail

ARCH="${1:-}"
case "$ARCH" in
  amd64|arm64) ;;
  *) echo "Aufruf: $0 amd64|arm64" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/.."

docker info > /dev/null 2>&1 || {
  echo "Docker läuft nicht – bitte Docker Desktop bzw. colima starten und das Skript erneut ausführen." >&2
  exit 1
}
mkdir -p dist

case "$(uname -m)" in
  arm64|aarch64) NATIV=arm64 ;;
  *) NATIV=amd64 ;;
esac

TAGS=(-t "vfm-pipeline:latest-${ARCH}")
if [ "$ARCH" = "$NATIV" ]; then
  TAGS+=(-t vfm-pipeline:latest)
fi

echo "==> Baue vfm-pipeline fuer linux/${ARCH} ..."
docker buildx build --platform "linux/${ARCH}" \
  --provenance=false --sbom=false "${TAGS[@]}" --load .

echo "==> Pruefe Architektur ..."
GEFUNDEN="$(docker image inspect "vfm-pipeline:latest-${ARCH}" --format '{{.Architecture}}')"
if [ "$GEFUNDEN" != "$ARCH" ]; then
  echo "FEHLER: Image hat Architektur '${GEFUNDEN}', erwartet '${ARCH}'." >&2
  exit 1
fi

echo "==> Exportiere dist/vfm-pipeline-${ARCH}.tar.gz ..."
docker save "vfm-pipeline:latest-${ARCH}" | gzip > "dist/vfm-pipeline-${ARCH}.tar.gz"
ls -lh "dist/vfm-pipeline-${ARCH}.tar.gz"
echo "OK: ${ARCH}"
