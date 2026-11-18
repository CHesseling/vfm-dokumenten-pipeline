"""Office-Dateien (docx, xlsx, pptx, html) per Docling als Markdown (Tabellen bleiben Tabellen).

Kein OCR und keine Modelle noetig; derselbe Converter wie fuer PDFs. Alte Formate
(.doc, .xls, .ppt) kann Docling nicht - die bleiben bewusst "sonstig".
"""

from io import BytesIO
from pathlib import PurePath

from app.ingest.pdf import ExtraktionsFehler, _docling_converter


def office_docling(inhalt: bytes, dateiname: str, artifacts_pfad: str) -> str:
    try:
        from docling.datamodel.base_models import DocumentStream

        endung = PurePath(dateiname).suffix.lower()
        ergebnis = _docling_converter(artifacts_pfad).convert(
            DocumentStream(name=f"dokument{endung}", stream=BytesIO(inhalt))
        )
        return ergebnis.document.export_to_markdown()
    except Exception as fehler:
        raise ExtraktionsFehler(f"Docling konnte {dateiname} nicht lesen: {fehler}") from fehler
