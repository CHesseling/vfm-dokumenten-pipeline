from app.enums import AnalyseArt
from tests.analyse.test_vergleich import CLEF, LLM, _analyse, _dok


def test_seite_zeigt_frage_und_beide_verfahren(client, session, einstellungen, tmp_path):
    k = tmp_path / "k.yaml"
    k.write_text("frage: Was ist das für ein <Dokument>?\nkategorien:\n  - name: Vertrag\n    beschreibung: Verträge\n",
                 encoding="utf-8")
    einstellungen.kategorien_pfad = str(k)
    a = _dok(session, "a.txt", "1")
    _analyse(session, a, AnalyseArt.KLASSIFIKATION, "chat-m", LLM, 4200)
    _analyse(session, a, AnalyseArt.KLASSIFIKATION_CLEF, "clef-flash:latest", CLEF, 120)
    session.commit()
    html = client.get("/klassifikation").text
    assert "Was ist das für ein &lt;Dokument&gt;?" in html and "Verträge" in html
    assert "a.txt" in html and "Vertrag" in html and "Rechnung" in html
    assert "4200 ms" in html and "120 ms" in html and "90 %" in html and "70 %" in html
    assert 'href="/klassifikation"' in html  # Navigation


def test_seite_ohne_clef_schluessel_hinweis(client, session):
    html = client.get("/klassifikation").text
    assert "CORTECS_API_KEY" in html


def test_detailseite_zeigt_beide(client, session):
    a = _dok(session, "a.txt", "1")
    _analyse(session, a, AnalyseArt.KLASSIFIKATION, "chat-m", LLM, 4200)
    _analyse(session, a, AnalyseArt.KLASSIFIKATION_CLEF, "clef-flash:latest", CLEF, 120)
    session.commit()
    html = client.get(f"/dokumente/{a.id}").text
    assert "Klassifikation: LLM und CLEF" in html
    assert "clef-flash:latest" in html and "4200 ms" in html and "120 ms" in html
    assert "Rechnung: 70 %" in html and "Klauseln" in html
