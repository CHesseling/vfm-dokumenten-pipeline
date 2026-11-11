import hashlib

from sqlmodel import select

from app.enums import DokumentTyp, ExtraktionsMethode
from app.ingest.speichern import (
    aktiv_setzen,
    dokument_speichern,
    extraktion_speichern,
    lesen_datei,
)
from app.models.auswertung import Chunk
from app.models.dokument import Dokument, TextExtraktion


def _text(n):
    return ("wort " * (n // 5 + 1))[:n]


def test_gleiche_datei_einmal(session, tmp_path):
    inhalt = b"%PDF-1.4 hallo"
    d1, neu1 = dokument_speichern(session, inhalt, "a.pdf", str(tmp_path))
    d2, neu2 = dokument_speichern(session, inhalt, "b.pdf", str(tmp_path))
    assert neu1 is True and neu2 is False
    assert d1.id == d2.id
    assert len(session.exec(select(Dokument)).all()) == 1
    sha = hashlib.sha256(inhalt).hexdigest()
    assert (tmp_path / sha[:2] / sha).exists()
    assert d1.typ == DokumentTyp.PDF
    assert lesen_datei(d1, str(tmp_path)) == inhalt


def test_leere_extraktion_ohne_chunks(session, einstellungen):
    dok, _ = dokument_speichern(session, b"x", "a.txt", einstellungen.daten_pfad)
    ex = extraktion_speichern(
        session, dok, ExtraktionsMethode.SCHNELL, "", None, 1, einstellungen
    )
    assert ex.ist_aktiv is True
    assert session.exec(select(Chunk)).all() == []


def test_aktive_extraktion_prioritaet(session, einstellungen):
    dok, _ = dokument_speichern(session, b"x", "a.txt", einstellungen.daten_pfad)
    schnell = extraktion_speichern(
        session, dok, ExtraktionsMethode.SCHNELL, _text(500), None, 1, einstellungen
    )
    docling = extraktion_speichern(
        session, dok, ExtraktionsMethode.DOCLING, _text(480), "d", 1, einstellungen
    )
    session.refresh(schnell)
    assert docling.ist_aktiv and not schnell.ist_aktiv
    chunks = session.exec(select(Chunk)).all()
    assert chunks and {c.textextraktion_id for c in chunks} == {docling.id}


def test_kurze_docling_verliert(session, einstellungen):
    dok, _ = dokument_speichern(session, b"x", "a.txt", einstellungen.daten_pfad)
    docling = extraktion_speichern(
        session, dok, ExtraktionsMethode.DOCLING, "kurz", "d", 1, einstellungen
    )
    schnell = extraktion_speichern(
        session, dok, ExtraktionsMethode.SCHNELL, _text(500), None, 1, einstellungen
    )
    session.refresh(docling)
    assert schnell.ist_aktiv and not docling.ist_aktiv


def test_ersetzen_gleicher_methode(session, einstellungen):
    dok, _ = dokument_speichern(session, b"x", "a.txt", einstellungen.daten_pfad)
    extraktion_speichern(
        session, dok, ExtraktionsMethode.SCHNELL, _text(500), None, 1, einstellungen
    )
    neu = extraktion_speichern(
        session, dok, ExtraktionsMethode.SCHNELL, _text(300), None, 1, einstellungen
    )
    assert len(session.exec(select(TextExtraktion)).all()) == 1
    assert neu.ist_aktiv
    chunks = session.exec(select(Chunk)).all()
    assert {c.textextraktion_id for c in chunks} == {neu.id}
    assert "".join(c.text for c in chunks)[:50] == _text(300)[:50]


def test_aktiv_setzen_manuell(session, einstellungen):
    dok, _ = dokument_speichern(session, b"x", "a.txt", einstellungen.daten_pfad)
    schnell = extraktion_speichern(
        session, dok, ExtraktionsMethode.SCHNELL, _text(500), None, 1, einstellungen
    )
    docling = extraktion_speichern(
        session, dok, ExtraktionsMethode.DOCLING, _text(480), "d", 1, einstellungen
    )
    aktiv_setzen(session, schnell.id, einstellungen)
    session.refresh(schnell)
    session.refresh(docling)
    assert schnell.ist_aktiv and not docling.ist_aktiv
    chunks = session.exec(select(Chunk)).all()
    assert {c.textextraktion_id for c in chunks} == {schnell.id}
