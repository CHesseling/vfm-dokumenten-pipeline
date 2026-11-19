"""Nur ein schweres lokales Modell rechnet zur Zeit (Docling-PDF, GLiNER, Whisper).

Gleichzeitig (z. B. Docling-OCR eines Scans und NER-Start in der Oberflaeche) reicht
der Speicher kleiner Rechner/VMs nicht: Der Kernel beendet den Prozess (Exit 137),
Oberflaeche und Terminal fallen mit. Die Sperre ist eine Datei-Sperre (flock) und
gilt damit fuer alle Threads UND Prozesse im Container, also auch fuer `vfm ...`
aus dem Browser-Terminal neben der Oberflaeche. Nicht verschachteln (kein Reentrant).
"""

import fcntl
import logging
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def _pfad() -> str:
    return os.environ.get("VFM_MODELL_SPERRE") or os.path.join(tempfile.gettempdir(), "vfm-modelle.lock")


@contextmanager
def modell_sperre(wer: str) -> Iterator[None]:
    with open(_pfad(), "a") as datei:
        start = time.monotonic()
        fcntl.flock(datei, fcntl.LOCK_EX)
        gewartet = time.monotonic() - start
        if gewartet > 1:
            logger.info("%s hat %.0f s auf ein anderes lokales Modell gewartet", wer, gewartet)
        try:
            yield
        finally:
            fcntl.flock(datei, fcntl.LOCK_UN)
