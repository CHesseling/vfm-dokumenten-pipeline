from app.enums import DokumentTyp
from app.ingest.dateitypen import erkenne_typ


def test_pdf_per_magic_bytes():
    typ, mime = erkenne_typ("scan.bin", b"%PDF-1.4 rest")
    assert typ == DokumentTyp.PDF
    assert mime == "application/pdf"


def test_unbekannt_ist_sonstig():
    typ, _ = erkenne_typ("x.docx", b"PK\x03\x04")
    assert typ == DokumentTyp.SONSTIG


def test_endungen():
    assert erkenne_typ("a.eml", b"From: x")[0] == DokumentTyp.EML
    assert erkenne_typ("a.M4A", b"x")[0] == DokumentTyp.AUDIO
    assert erkenne_typ("a.heic", b"x")[0] == DokumentTyp.BILD
    assert erkenne_typ("a.md", b"x")[0] == DokumentTyp.TEXT
