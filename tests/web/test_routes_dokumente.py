from pathlib import Path

from app.enums import ExtraktionsMethode, DokumentTyp
from app.ingest.speichern import dokument_speichern, extraktion_speichern
from tests.fixtures.pdf_bauen import mini_pdf


def _pdf_dokument(session, s, name="bericht.pdf"):
    inhalt = mini_pdf([["Hallo Welt"]])
    dok, _ = dokument_speichern(session, inhalt, name, s.daten_pfad)
    extraktion_speichern(session, dok, ExtraktionsMethode.SCHNELL, "Text schnell", None, 5, s)
    extraktion_speichern(session, dok, ExtraktionsMethode.DOCLING, "Text docling", "docling", 9, s)
    session.commit()
    return dok


def test_startseite_leitet_um(client):
    assert client.get("/").headers["location"] == "/dokumente"


def test_liste_zeigt_dokument(client, session, einstellungen):
    _pdf_dokument(session, einstellungen, "<b>akte</b>.pdf")
    html = client.get("/dokumente").text
    assert "&lt;b&gt;akte&lt;/b&gt;.pdf" in html
    assert "<b>akte</b>" not in html


def test_liste_filtert(client, session, einstellungen):
    _pdf_dokument(session, einstellungen, "bericht.pdf")
    assert "bericht.pdf" not in client.get("/dokumente?q=xyz").text
    assert "bericht.pdf" in client.get("/dokumente?q=BERI&typ=pdf").text
    assert "bericht.pdf" not in client.get("/dokumente?typ=audio").text


def test_detail_zeigt_beide_methoden(client, session, einstellungen):
    dok = _pdf_dokument(session, einstellungen)
    html = client.get(f"/dokumente/{dok.id}").text
    assert "schnell" in html and "docling" in html
    assert "Text docling" in html
    assert "<iframe" in html
    assert f"/dokumente/{dok.id}/datei" in html
    assert "als aktiv setzen" in html


def test_detail_unbekannt_404(client):
    assert client.get("/dokumente/999999").status_code == 404


def test_aktiv_setzen(client, session, einstellungen):
    from app.models import TextExtraktion
    from sqlmodel import select

    dok = _pdf_dokument(session, einstellungen)
    docling = session.exec(
        select(TextExtraktion).where(TextExtraktion.methode == ExtraktionsMethode.DOCLING)
    ).one()
    antwort = client.post(f"/dokumente/{dok.id}/aktiv/{docling.id}")
    assert antwort.status_code == 303
    assert antwort.headers["location"] == f"/dokumente/{dok.id}"
    session.refresh(docling)
    assert docling.ist_aktiv


def test_datei_auslieferung_mime(client, session, einstellungen):
    dok = _pdf_dokument(session, einstellungen, "Prüfbericht.pdf")
    antwort = client.get(f"/dokumente/{dok.id}/datei")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "application/pdf"
    assert antwort.headers["content-disposition"].startswith("inline; filename*=UTF-8''")
    assert "Pr%C3%BCfbericht.pdf" in antwort.headers["content-disposition"]
    assert antwort.content.startswith(b"%PDF")


def test_datei_fehlt_auf_platte_404(client, session, einstellungen):
    dok = _pdf_dokument(session, einstellungen)
    Path(dok.dateipfad(einstellungen.daten_pfad)).unlink()
    assert client.get(f"/dokumente/{dok.id}/datei").status_code == 404


def test_mail_detail_zeigt_kopf_und_anhaenge(client, session, einstellungen):
    mail, _ = dokument_speichern(
        session, b"From: a@b.de\r\n\r\nHi", "post.eml", einstellungen.daten_pfad,
        metadaten={"absender": "a@b.de", "betreff": "Betreff X", "datum": "2026-01-01"},
    )
    anhang, _ = dokument_speichern(
        session, mini_pdf([["x"]]), "anlage.pdf", einstellungen.daten_pfad, parent_id=mail.id
    )
    session.commit()
    assert mail.typ == DokumentTyp.EML
    html = client.get(f"/dokumente/{mail.id}").text
    assert "Betreff X" in html and "a@b.de" in html
    assert f"/dokumente/{anhang.id}" in html
    assert "anlage.pdf" in client.get("/dokumente").text


# --- Analysen (Task 22) ---

def _dok_mit_text(session, name="a.txt", sha="1", typ=None, kat=None):
    from app.enums import AnalyseArt, DokumentTyp, ExtraktionsMethode
    from app.models import Analyse, Dokument, TextExtraktion

    d = Dokument(sha256=sha, dateiname=name, typ=typ or DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    session.add(TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text="Hallo Welt", ist_aktiv=True))
    if kat:
        session.add(Analyse(dokument_id=d.id, art=AnalyseArt.KLASSIFIKATION, modell="m",
                            ergebnis={"kategorie": kat, "begruendung": "Weil <b>darum</b>", "sicherheit": 0.8}))
    session.commit()
    return d


def test_detail_zeigt_analysen(client, session):
    from app.enums import AnalyseArt
    from app.models import Analyse

    d = _dok_mit_text(session, kat="Vertrag")
    session.add(Analyse(dokument_id=d.id, art=AnalyseArt.ZUSAMMENFASSUNG, modell="m", ergebnis={"text": "Kurz & knapp."}))
    session.add(Analyse(dokument_id=d.id, art=AnalyseArt.BILDBESCHREIBUNG, modell="m", ergebnis={"text": "Ein Hund."}))
    session.commit()
    html = client.get(f"/dokumente/{d.id}").text
    assert "Kurz &amp; knapp." in html and "Ein Hund." in html
    assert "Vertrag" in html and "80" in html and "Weil &lt;b&gt;darum" in html
    assert "Analysieren" in html


def test_analyse_starten(client, session, monkeypatch):
    import app.web.routes_dokumente as rd
    from app.analyse.ablauf import AnalyseBilanz
    from app.enums import AnalyseArt

    d = _dok_mit_text(session)
    aufrufe = []
    monkeypatch.setattr(rd, "analyse_ausfuehren",
                        lambda session, s, arten, dokument_id=None, **k: aufrufe.append((arten, dokument_id, k)) or AnalyseBilanz())
    r = client.post(f"/dokumente/{d.id}/analyse")
    assert r.status_code == 303 and r.headers["location"] == f"/dokumente/{d.id}"
    assert aufrufe == [(set(AnalyseArt), d.id, {"nur_fehlende": False})]  # Einzel-Button rechnet neu


def test_analyse_fehler_fester_text(client, session, monkeypatch):
    import app.web.routes_dokumente as rd
    from app.analyse.ablauf import AnalyseBilanz

    d = _dok_mit_text(session)
    monkeypatch.setattr(rd, "analyse_ausfuehren", lambda *a, **k: AnalyseBilanz(fehler=1))
    r = client.post(f"/dokumente/{d.id}/analyse")
    assert r.status_code == 303 and "analyse_fehler=1" in r.headers["location"]
    html = client.get(r.headers["location"]).text
    assert "Läufe" in html and "fehlgeschlagen" in html
    # beliebiger Text aus dem Querystring wird nicht gespiegelt
    assert "EVIL" not in client.get(f"/dokumente/{d.id}?analyse_fehler=EVIL&ner_fehler=EVIL").text


def test_analyse_unbekannt_404(client):
    assert client.post("/dokumente/99999/analyse").status_code == 404


def test_liste_kategorie_spalte_und_filter(client, session):
    _dok_mit_text(session, "vertrag.txt", "1", kat="Vertrag")
    _dok_mit_text(session, "rest.txt", "2", kat="Rechnung")
    _dok_mit_text(session, "ohne.txt", "3")
    html = client.get("/dokumente").text
    assert "Kategorie" in html and "Vertrag" in html and "Rechnung" in html
    gefiltert = client.get("/dokumente?kategorie=Vertrag").text
    assert "vertrag.txt" in gefiltert and "rest.txt" not in gefiltert and "ohne.txt" not in gefiltert


def _dok_mit_embeddings(session):
    from app.models import Chunk, Dokument, Embedding, TextExtraktion

    d = Dokument(sha256="e1", dateiname="e.txt", typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    ex = TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text="eins", ist_aktiv=True)
    session.add(ex)
    session.flush()
    c = Chunk(textextraktion_id=ex.id, position=0, start=0, ende=4, text="eins")
    session.add(c)
    session.flush()
    for modell in ("embed-m", "anderes"):
        session.add(Embedding(chunk_id=c.id, modell=modell, vektor=[1.0, 2.0]))
    session.commit()
    return d


def test_embeddings_loeschen_route(client, session):
    from sqlmodel import select

    from app.models import Embedding

    d = _dok_mit_embeddings(session)
    assert "Embeddings: 1 (Modell embed-m), 2 (alle Modelle)" in client.get(f"/dokumente/{d.id}").text
    r = client.post(f"/dokumente/{d.id}/embeddings/loeschen", data={"umfang": "aktuell"})
    assert r.status_code == 303 and r.headers["location"] == f"/dokumente/{d.id}"
    assert [e.modell for e in session.exec(select(Embedding)).all()] == ["anderes"]
    assert "Embeddings: 0 (Modell embed-m), 1 (alle Modelle)" in client.get(f"/dokumente/{d.id}").text
    assert client.post(f"/dokumente/{d.id}/embeddings/loeschen", data={"umfang": "x"}).status_code == 400
    client.post(f"/dokumente/{d.id}/embeddings/loeschen", data={"umfang": "alle"})
    assert session.exec(select(Embedding)).all() == []
    assert client.post("/dokumente/99999/embeddings/loeschen", data={"umfang": "alle"}).status_code == 404


def test_detail_formular_vorbelegt(client, session):
    d = _dok_mit_embeddings(session)
    html = client.get(f"/dokumente/{d.id}").text
    assert 'value="person, organisation, ort, datum, geldbetrag, iban, telefon, email"' in html
    assert 'name="schwelle"' in html and 'value="0.5"' in html and 'step="any"' in html
