"""Bilder: Metadaten (EXIF), JPEG-Normalisierung und Texterkennung per Vision-Modell."""

import io
from datetime import datetime

import pillow_heif
from PIL import Image, ImageOps

from app.ingest.pdf import VISION_TRANSKRIPTION_PROMPT
from app.providers.llm_client import LLMClient, bild_nachricht

pillow_heif.register_heif_opener()

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825


def _dezimalgrad(dms, ref) -> float | None:
    try:
        grad, minuten, sekunden = (float(x) for x in dms)
    except (TypeError, ValueError):
        return None
    wert = grad + minuten / 60 + sekunden / 3600
    if str(ref).upper() in ("S", "W"):
        wert = -wert
    return round(wert, 6)


def _aufnahmedatum(roh) -> str | None:
    try:
        return datetime.strptime(str(roh).strip(), "%Y:%m:%d %H:%M:%S").isoformat()
    except ValueError:
        return None


def bild_metadaten(inhalt: bytes) -> dict:
    bild = Image.open(io.BytesIO(inhalt))
    meta: dict = {"breite": bild.width, "hoehe": bild.height}
    try:
        exif = bild.getexif()
        exif_ifd = exif.get_ifd(_EXIF_IFD)
        gps = exif.get_ifd(_GPS_IFD)
    except Exception:
        return meta

    roh_datum = exif_ifd.get(0x9003) or exif.get(0x0132)
    datum = _aufnahmedatum(roh_datum) if roh_datum else None
    if datum:
        meta["aufnahmedatum"] = datum
    if exif.get(0x010F):
        meta["kamera_marke"] = str(exif[0x010F]).strip()
    if exif.get(0x0110):
        meta["kamera_modell"] = str(exif[0x0110]).strip()
    if gps and 2 in gps and 4 in gps:
        lat = _dezimalgrad(gps[2], gps.get(1, "N"))
        lon = _dezimalgrad(gps[4], gps.get(3, "E"))
        if lat is not None and lon is not None:
            meta["gps"] = {"lat": lat, "lon": lon}
    return meta


def bild_als_jpeg(inhalt: bytes, max_kante: int = 2048) -> bytes:
    bild = ImageOps.exif_transpose(Image.open(io.BytesIO(inhalt)))
    bild = bild.convert("RGB")
    bild.thumbnail((max_kante, max_kante))
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=90)
    return puffer.getvalue()


def bild_ocr(inhalt: bytes, client: LLMClient) -> str:
    jpeg = bild_als_jpeg(inhalt)
    return client.chat_text([bild_nachricht(VISION_TRANSKRIPTION_PROMPT, [(jpeg, "image/jpeg")])])
