import io
import re

import pypdfium2 as pdfium
from pypdfium2._helpers.misc import PdfiumError


def pdf_seitenzahl(pdf_bytes: bytes) -> int:
    try:
        return len(pdfium.PdfDocument(pdf_bytes))
    except PdfiumError:
        return 0


def render_pdf_pages_to_png(pdf_bytes: bytes, scale: float = 2.0, max_seiten: int | None = None) -> list[bytes]:
    """Rendert die Seiten als PNG; mit max_seiten nur die ersten (Rendern ist teuer)."""
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except PdfiumError:
        return []

    bilder = []
    for nummer, seite in enumerate(pdf):
        if max_seiten is not None and nummer >= max_seiten:
            break
        bitmap = seite.render(scale=scale)
        pil_bild = bitmap.to_pil()
        puffer = io.BytesIO()
        pil_bild.save(puffer, format="PNG")
        bilder.append(puffer.getvalue())
    return bilder


def bereinige_pdf_text(text: str) -> str:
    """pdfium liefert weiche Trennstellen am Zeilenende als U+FFFE
    ("Termins\ufffestunde", "Wohnungseinbruchs\ufffe\r\ndiebstahl") - das
    Wort wird zusammengefuegt, sonst landen Artefakte in Delikten/Namen."""
    return re.sub(r"\ufffe\s*", "", text)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extrahiert den Text aller Seiten eines PDFs in Lesereihenfolge.

    Fuer PDFs mit echter Textebene (der Regelfall bei Wochenplaenen) deutlich
    guenstiger und zuverlaessiger als der Umweg ueber ein Vision-Modell -
    pypdfium2 erhaelt dabei sogar verschachtelte Tabellenspalten (mehrere
    Fortsetzungstermine in einer Zelle) in korrekter Reihenfolge. Liefert ""
    bei einem ungueltigen PDF oder einem PDF ohne Textebene (z. B. Scan)."""
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except PdfiumError:
        return ""

    seiten_texte = []
    for seite in pdf:
        textpage = seite.get_textpage()
        seiten_texte.append(textpage.get_text_range())
    return bereinige_pdf_text("\n\n".join(seiten_texte)).strip()
