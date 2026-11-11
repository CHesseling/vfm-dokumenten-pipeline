from app.ingest.pdf_render import extract_pdf_text, render_pdf_pages_to_png
from tests.fixtures.pdf_bauen import mini_pdf

SEITEN = [
    ["Wochenplan", "Aktenzeichen 502 KLs 19/26", "Montag, den 07. September 2026"],
    ["Seite zwei", "525 KLs 11/26", "09.09.2026", "14.09.2026", "17.09.2026"],
    ["Seite drei", "Ende"],
]


def test_rendert_alle_seiten_als_png():
    seiten = render_pdf_pages_to_png(mini_pdf(SEITEN))
    assert len(seiten) == 3
    for seite in seiten:
        assert seite.startswith(b"\x89PNG\r\n\x1a\n")


def test_leeres_pdf_liefert_leere_liste():
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"trailer<</Root 1 0 R>>"
    )
    assert render_pdf_pages_to_png(minimal_pdf) == []


def test_extract_pdf_text_enthaelt_kerninhalte():
    text = extract_pdf_text(mini_pdf(SEITEN))

    assert "Wochenplan" in text
    assert "502 KLs 19/26" in text
    assert "Montag, den 07. September 2026" in text


def test_extract_pdf_text_erhaelt_zeilen_und_seiten_in_reihenfolge():
    text = extract_pdf_text(mini_pdf(SEITEN))

    idx = text.find("525 KLs 11/26")
    assert idx != -1
    ausschnitt = text[idx : idx + 400]
    for datum in ["09.09.2026", "14.09.2026", "17.09.2026"]:
        assert datum in ausschnitt
    assert text.index("Wochenplan") < text.index("Seite zwei") < text.index("Seite drei")


def test_extract_pdf_text_bei_ungueltigem_pdf_liefert_leeren_string():
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"trailer<</Root 1 0 R>>"
    )
    assert extract_pdf_text(minimal_pdf) == ""


def test_bereinige_pdf_text_entfernt_trennzeichen_artefakte():
    from app.ingest.pdf_render import bereinige_pdf_text

    assert bereinige_pdf_text("Termins￾stunde, Wohnungseinbruchs￾\r\ndiebstahl") == "Terminsstunde, Wohnungseinbruchsdiebstahl"


def test_rendert_nur_max_seiten():
    from app.ingest.pdf_render import pdf_seitenzahl

    pdf = mini_pdf(SEITEN)
    assert len(render_pdf_pages_to_png(pdf, max_seiten=1)) == 1
    assert pdf_seitenzahl(pdf) == 3
    assert pdf_seitenzahl(b"kein pdf") == 0
