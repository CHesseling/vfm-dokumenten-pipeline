#!/usr/bin/env bash
# Baut das App-Image fuer eine Architektur und exportiert es nach dist/.
# Aufruf: scripts/image_bauen.sh amd64|arm64
# Ergebnis: vfm-pipeline:latest-<arch> (lokal), dist/vfm-pipeline-<arch>.tar.gz.
# "vfm-pipeline:latest" wird nur gesetzt, wenn <arch> der Host-Architektur
# entspricht (sonst liefe die lokale Entwicklung unter Emulation).
# Laeuft mit Docker (buildx) oder Podman; VFM_ENGINE=docker|podman erzwingt eine.
set -euo pipefail

ARCH="${1:-}"
case "$ARCH" in
  amd64|arm64) ;;
  *) echo "Aufruf: $0 amd64|arm64" >&2; exit 2 ;;
esac

cd "$(dirname "$0")/.."

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
mkdir -p dist

case "$(uname -m)" in
  arm64|aarch64) NATIV=arm64 ;;
  *) NATIV=amd64 ;;
esac

# Podman wuerde sonst unter localhost/ taggen; docker.io/library/ laedt
# Docker spaeter als schlichtes "vfm-pipeline:...", Podman findet beides.
if [ "$CE" = podman ]; then PRAEFIX=docker.io/library/; else PRAEFIX=""; fi
TAGS=(-t "${PRAEFIX}vfm-pipeline:latest-${ARCH}")
if [ "$ARCH" = "$NATIV" ]; then
  TAGS+=(-t "${PRAEFIX}vfm-pipeline:latest")
fi

echo "==> Baue vfm-pipeline fuer linux/${ARCH} ($CE) ..."
if [ "$CE" = podman ]; then
  # Fremdarchitektur braucht qemu-user-static (in der Podman-Machine enthalten)
  podman build --platform "linux/${ARCH}" "${TAGS[@]}" .
else
  docker buildx build --platform "linux/${ARCH}" \
    --provenance=false --sbom=false "${TAGS[@]}" --load .
fi

echo "==> Pruefe Architektur ..."
GEFUNDEN="$("$CE" image inspect "${PRAEFIX}vfm-pipeline:latest-${ARCH}" --format '{{.Architecture}}')"
if [ "$GEFUNDEN" != "$ARCH" ]; then
  echo "FEHLER: Image hat Architektur '${GEFUNDEN}', erwartet '${ARCH}'." >&2
  exit 1
fi

echo "==> Exportiere dist/vfm-pipeline-${ARCH}.tar.gz ..."
"$CE" save "${PRAEFIX}vfm-pipeline:latest-${ARCH}" | gzip > "dist/vfm-pipeline-${ARCH}.tar.gz"
ls -lh "dist/vfm-pipeline-${ARCH}.tar.gz"
echo "OK: ${ARCH}"
