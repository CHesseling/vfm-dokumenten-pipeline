"""Test-Helfer: PDFs von Hand bauen (keine zusaetzliche Abhaengigkeit)."""

import io

from PIL import Image

from app.ingest.pdf_render import render_pdf_pages_to_png


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def mini_pdf(seiten: list[list[str]]) -> bytes:
    """Gueltiges PDF mit Textebene (Helvetica); ein Listeneintrag = eine Textzeile."""
    n = len(seiten)
    # Objekte: 1 Katalog, 2 Pages, 3 Font, dann je Seite (Page, Content)
    objekte: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    kids = []
    for i, zeilen in enumerate(seiten):
        page_nr, content_nr = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_nr} 0 R")
        befehle = ["BT", "/F1 14 Tf", "50 780 Td", "18 TL"]
        for zeile in zeilen:
            befehle.append(f"({_escape(zeile)}) Tj T*")
        befehle.append("ET")
        stream = "\n".join(befehle).encode("cp1252")
        objekte[page_nr] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_nr} 0 R >>"
        ).encode()
        objekte[content_nr] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    objekte[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for nr in sorted(objekte):
        offsets[nr] = len(out)
        out += b"%d 0 obj\n" % nr + objekte[nr] + b"\nendobj\n"
    xref_pos = len(out)
    gesamt = max(objekte) + 1
    out += b"xref\n0 %d\n" % gesamt
    out += b"0000000000 65535 f \n"
    for nr in range(1, gesamt):
        out += b"%010d 00000 n \n" % offsets[nr]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (gesamt, xref_pos)
    return bytes(out)


def scan_pdf(pdf: bytes) -> bytes:
    """Rendert ein PDF zu Bildern und speichert diese als PDF ohne Textebene."""
    bilder = [Image.open(io.BytesIO(png)).convert("RGB") for png in render_pdf_pages_to_png(pdf)]
    puffer = io.BytesIO()
    bilder[0].save(puffer, format="PDF", save_all=True, append_images=bilder[1:])
    return puffer.getvalue()
