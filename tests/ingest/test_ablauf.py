import email.message
from pathlib import Path

import pytest
from sqlmodel import select

from app.enums import DokumentTyp, ExtraktionsMethode, LaufStatus
from app.ingest import ablauf
from app.ingest.ablauf import IngestClients, dateien_finden, ingest_datei, ingest_ordner
from app.models import Dokument, Lauf, TextExtraktion
from tests.fixtures.pdf_bauen import mini_pdf


class FakeVision:
    model = "vision-m"

    def chat_text(self, *a, **k):
        return "Vision-Text"


class FakeTrans:
    model = "whisper-m"

    def transkribieren(self, inhalt, dateiname):
        return "Das ist ein transkribierter Text."


@pytest.fixture
def clients():
    return IngestClients(vision=FakeVision(), transkribierer=FakeTrans())


@pytest.fixture(autouse=True)
def kein_docling(monkeypatch):
    aufrufe = []

    def fake(inhalt, pfad):
        aufrufe.append(1)
        return "Docling-Text " * 5

    monkeypatch.setattr(ablauf, "pdf_docling", fake)
    return aufrufe


def _laeufe(session):
    return session.exec(select(Lauf)).all()


def test_kaputtes_pdf_bricht_nicht_ab(session, einstellungen, clients, tmp_path, monkeypatch):
    def kaputt(inhalt, pfad):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(ablauf, "pdf_docling", kaputt)
    ordner = tmp_path / "material"
    ordner.mkdir()
    (ordner / "kaputt.pdf").write_bytes(b"%PDF" + b"\x00garbage" * 10)
    (ordner / "notiz.txt").write_text("Eine Notiz mit genug Text für die Extraktion.")
    bilanz = ingest_ordner(session, ordner, einstellungen, clients)
    assert bilanz.neu == 2 and bilanz.fehler == 0
    txt = session.exec(select(Dokument).where(Dokument.dateiname == "notiz.txt")).one()
    assert session.exec(
        select(TextExtraktion).where(TextExtraktion.dokument_id == txt.id, TextExtraktion.ist_aktiv.is_(True))
    ).first()
    pdf = session.exec(select(Dokument).where(Dokument.dateiname == "kaputt.pdf")).one()
    laeufe = {l.schritt: l for l in _laeufe(session) if l.dokument_id == pdf.id}
    assert laeufe["extraktion:schnell"].status == LaufStatus.ERFOLG
    assert laeufe["extraktion:docling"].status == LaufStatus.FEHLER
    assert "kaputt" in laeufe["extraktion:docling"].fehler
    extraktionen = session.exec(select(TextExtraktion).where(TextExtraktion.dokument_id == pdf.id)).all()
    assert [(e.methode, e.text) for e in extraktionen] == [(ExtraktionsMethode.SCHNELL, "")]


def test_altes_doc_wird_uebersprungen(session, einstellungen, clients):
    d = ingest_datei(session, b"\xd0\xcf\x11\xe0doc", "a.doc", einstellungen, clients)
    assert d.typ == DokumentTyp.SONSTIG
    laeufe = _laeufe(session)
    assert len(laeufe) == 1
    assert laeufe[0].status == LaufStatus.UEBERSPRUNGEN
    assert laeufe[0].fehler == "Dateityp nicht unterstützt"


def _mail(anhang: bytes) -> bytes:
    m = email.message.EmailMessage()
    m["From"] = "a@x.de"
    m["To"] = "b@x.de"
    m["Subject"] = "Test"
    m["Date"] = "Mon, 10 Nov 2026 10:00:00 +0100"
    m.set_content("Hallo, anbei die Unterlagen zur Sache.")
    m.add_attachment(anhang, maintype="application", subtype="pdf", filename="a.pdf")
    return m.as_bytes()


def test_anhang_und_einzeldatei_ein_dokument(session, einstellungen, clients, tmp_path):
    pdf = mini_pdf([["Seite eins mit etwas Text"]])
    ordner = tmp_path / "m"
    ordner.mkdir()
    (ordner / "1_mail.eml").write_bytes(_mail(pdf))
    (ordner / "2_a.pdf").write_bytes(pdf)
    bilanz = ingest_ordner(session, ordner, einstellungen, clients)
    pdfs = session.exec(select(Dokument).where(Dokument.typ == DokumentTyp.PDF)).all()
    assert len(pdfs) == 1
    mail = session.exec(select(Dokument).where(Dokument.typ == DokumentTyp.EML)).one()
    assert pdfs[0].parent_id == mail.id
    assert bilanz.neu == 1 and bilanz.bekannt == 1
    assert mail.metadaten["betreff"] == "Test"


def test_scan_pdf_loest_docling_aus(session, einstellungen, clients, monkeypatch, kein_docling):
    monkeypatch.setattr(ablauf, "pdf_schnell", lambda inhalt: "kurz")
    ingest_datei(session, mini_pdf([["x"]]), "s.pdf", einstellungen, clients)
    assert kein_docling
    methoden = {e.methode for e in session.exec(select(TextExtraktion)).all()}
    assert methoden == {ExtraktionsMethode.SCHNELL, ExtraktionsMethode.DOCLING}


def test_pdf_alle_methoden(session, einstellungen, clients):
    ingest_datei(session, mini_pdf([["Text " * 80]]), "s.pdf", einstellungen, clients, methoden={"alle"})
    methoden = {e.methode for e in session.exec(select(TextExtraktion)).all()}
    assert methoden == {ExtraktionsMethode.SCHNELL, ExtraktionsMethode.DOCLING, ExtraktionsMethode.VISION}
    modelle = {l.modell for l in _laeufe(session)}
    assert modelle == {None, "docling", "vision-m"}


def test_zweiter_lauf_ueberspringt(session, einstellungen, clients, tmp_path):
    ordner = tmp_path / "m"
    ordner.mkdir()
    (ordner / "a.txt").write_text("Text eins, lang genug für die Extraktion.")
    (ordner / "b.txt").write_text("Text zwei, ebenfalls lang genug dafür.")
    assert ingest_ordner(session, ordner, einstellungen, clients).neu == 2
    anzahl = len(_laeufe(session))
    b = ingest_ordner(session, ordner, einstellungen, clients)
    assert (b.neu, b.bekannt) == (0, 2)
    assert len(_laeufe(session)) == anzahl


def test_audio_und_bild(session, einstellungen, clients, monkeypatch):
    monkeypatch.setattr(ablauf, "bild_ocr", lambda inhalt, c: "Bildtext")
    monkeypatch.setattr(ablauf, "bild_metadaten", lambda inhalt: {"breite": 1})
    d = ingest_datei(session, b"\xff\xd8\xffxx", "f.jpg", einstellungen, clients)
    assert d.metadaten == {"breite": 1}
    a = ingest_datei(session, b"ID3\x03audio", "a.mp3", einstellungen, clients)
    assert a.typ == DokumentTyp.AUDIO
    ex = session.exec(select(TextExtraktion).where(TextExtraktion.dokument_id == a.id)).one()
    assert ex.methode == ExtraktionsMethode.WHISPER and ex.modell == "whisper-m"


def test_dateien_finden(tmp_path):
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "x.txt").write_text("x")
    (tmp_path / ".versteckt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("x")
    (tmp_path / "a.txt").write_text("x")
    assert [p.name for p in dateien_finden(tmp_path)] == ["a.txt", "b.txt"]


def test_vision_providerfehler_bei_bild(session, einstellungen, monkeypatch):
    from app.providers.llm_client import ProviderFehler

    class Kaputt:
        model = "m"

        def chat_text(self, *a, **k):
            raise ProviderFehler(rolle="vision", base_url="http://x", modell="m", meldung="nicht erreichbar")

    monkeypatch.setattr(ablauf, "bild_ocr", lambda inhalt, c: c.chat_text([]))
    monkeypatch.setattr(ablauf, "bild_metadaten", lambda inhalt: {})
    c = IngestClients(vision=Kaputt(), transkribierer=FakeTrans())
    d = ingest_datei(session, b"\xff\xd8\xffyy", "f.jpg", einstellungen, c)
    laeufe = [l for l in _laeufe(session) if l.dokument_id == d.id]
    assert len(laeufe) == 1 and laeufe[0].status == LaufStatus.FEHLER
    assert "nicht erreichbar" in laeufe[0].fehler


def test_transkription_fehler_bei_audio(session, einstellungen):
    class Kaputt:
        model = "w"

        def transkribieren(self, inhalt, dateiname):
            raise RuntimeError("Modell nicht erreichbar")

    c = IngestClients(vision=FakeVision(), transkribierer=Kaputt())
    d = ingest_datei(session, b"\x00\x00\x00\x20ftypM4A \x00audio", "a.m4a", einstellungen, c)
    assert d.typ == DokumentTyp.AUDIO
    laeufe = [l for l in _laeufe(session) if l.dokument_id == d.id]
    assert len(laeufe) == 1 and laeufe[0].status == LaufStatus.FEHLER
    assert "nicht erreichbar" in laeufe[0].fehler


def test_leere_textdatei(session, einstellungen, clients):
    from app.models import Chunk

    d = ingest_datei(session, b"", "leer.txt", einstellungen, clients)
    ex = session.exec(select(TextExtraktion).where(TextExtraktion.dokument_id == d.id)).one()
    assert ex.text == ""
    assert session.exec(select(Chunk)).all() == []


def _png() -> bytes:
    import io

    from PIL import Image

    puffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(puffer, format="PNG")
    return puffer.getvalue()


def test_ordner_import_zaehlt_datei_mit_nur_fehlern(session, einstellungen, tmp_path):
    class KaputteVision:
        model = "vision-m"

        def chat_text(self, *a, **k):
            raise RuntimeError("Vision down")

    clients = IngestClients(vision=KaputteVision(), transkribierer=FakeTrans())
    ordner = tmp_path / "m"
    ordner.mkdir()
    (ordner / "bild.png").write_bytes(_png())
    bilanz = ingest_ordner(session, ordner, einstellungen, clients)
    assert bilanz.fehler == 1 and bilanz.neu == 0
    assert [l.status for l in _laeufe(session)] == [LaufStatus.FEHLER]


def test_datei_mit_teilerfolg_ist_kein_fehler(session, einstellungen, clients, monkeypatch):
    monkeypatch.setattr(ablauf, "pdf_schnell", lambda inhalt: "kurz")  # loest docling aus
    monkeypatch.setattr(ablauf, "pdf_docling", lambda inhalt, pfad: (_ for _ in ()).throw(RuntimeError("x")))
    ergebnis = ablauf.ingest_datei_mit_ergebnis(session, mini_pdf([["x"]]), "s.pdf", einstellungen, clients)
    assert ergebnis.fehlgeschlagen is False


def test_office_ueber_docling(session, einstellungen, clients, monkeypatch):
    erhalten = []
    monkeypatch.setattr(ablauf, "office_docling", lambda inhalt, name, pfad: erhalten.append(name) or "| Tabelle |")
    d = ingest_datei(session, b"PK\x03\x04docx", "bericht.docx", einstellungen, clients)
    ex = session.exec(select(TextExtraktion).where(TextExtraktion.dokument_id == d.id)).one()
    assert d.typ == DokumentTyp.OFFICE and ex.methode == ExtraktionsMethode.DOCLING and ex.ist_aktiv
    assert ex.text == "| Tabelle |" and erhalten == ["bericht.docx"]


def test_video_ueber_whisper(session, einstellungen, clients):
    d = ingest_datei(session, b"\x00\x00\x00\x18ftypmp42video", "interview.mp4", einstellungen, clients)
    ex = session.exec(select(TextExtraktion).where(TextExtraktion.dokument_id == d.id)).one()
    assert d.typ == DokumentTyp.VIDEO and ex.methode == ExtraktionsMethode.WHISPER and ex.modell == "whisper-m"
    assert ex.text == "Das ist ein transkribierter Text." and ex.ist_aktiv
