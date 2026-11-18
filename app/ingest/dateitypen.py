"""Dateityp-Erkennung: Magic Bytes vor Dateiendung."""

from pathlib import PurePath

from app.enums import DokumentTyp

_ENDUNGEN: list[tuple[DokumentTyp, set[str]]] = [
    (DokumentTyp.EML, {".eml"}),
    (DokumentTyp.AUDIO, {".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aac", ".amr"}),
    (
        DokumentTyp.BILD,
        {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"},
    ),
    (DokumentTyp.TEXT, {".txt", ".md", ".csv"}),
    # Docling; altes .doc/.xls/.ppt bewusst nicht (braeuchte LibreOffice)
    (DokumentTyp.OFFICE, {".docx", ".xlsx", ".pptx", ".html", ".htm"}),
    # Whisper liest die Tonspur direkt aus dem Container (ffmpeg/PyAV)
    (DokumentTyp.VIDEO, {".mp4", ".mov", ".m4v", ".webm", ".mkv"}),
]

_MIME = {
    ".pdf": "application/pdf",
    ".eml": "message/rfc822",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".amr": "audio/amr",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".html": "text/html",
    ".htm": "text/html",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}


def erkenne_typ(dateiname: str, inhalt: bytes) -> tuple[DokumentTyp, str]:
    """Liefert (Typ, MIME). Magic Bytes haben Vorrang vor der Endung."""
    if inhalt.startswith(b"%PDF"):
        return DokumentTyp.PDF, "application/pdf"
    endung = PurePath(dateiname).suffix.lower()
    for typ, endungen in _ENDUNGEN:
        if endung in endungen:
            return typ, _MIME[endung]
    return DokumentTyp.SONSTIG, "application/octet-stream"
