import io

import pytest
from docx import Document

from app.ingest.office import office_docling
from app.ingest.pdf import ExtraktionsFehler


def test_docx_mit_tabelle(tmp_path):
    d = Document()
    d.add_heading("Vertrag Nordlicht", 1)
    d.add_paragraph("Anna Meier unterschreibt.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Posten", "Betrag"
    t.cell(1, 0).text, t.cell(1, 1).text = "Lager", "1.200 €"
    puffer = io.BytesIO()
    d.save(puffer)
    text = office_docling(puffer.getvalue(), "vertrag.docx", str(tmp_path))
    assert "Vertrag Nordlicht" in text and "Anna Meier" in text
    assert "| Lager" in text and "1.200 €" in text  # Tabelle als Markdown


def test_kaputte_datei_lesbarer_fehler(tmp_path):
    with pytest.raises(ExtraktionsFehler, match="vertrag.docx"):
        office_docling(b"kein zip", "vertrag.docx", str(tmp_path))
