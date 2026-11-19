"""Dokumente und Textextraktionen speichern.

Alle Funktionen führen nur ``flush`` aus, kein ``commit`` - Aufrufer
(Ingest-Ablauf, GUI) committen.
"""

import hashlib

from sqlalchemy import delete
from sqlmodel import Session, select

from app.config import Settings
from app.enums import ExtraktionsMethode
from app.ingest.chunking import chunken
from app.ingest.dateitypen import erkenne_typ
from app.models.auswertung import Chunk
from app.models.dokument import Dokument, TextExtraktion

PRIORITAET = [
    ExtraktionsMethode.DOCLING,
    ExtraktionsMethode.EML,
    ExtraktionsMethode.TEXT,
    ExtraktionsMethode.WHISPER,
    ExtraktionsMethode.SCHNELL,
    ExtraktionsMethode.VISION,
]
MINDESTLAENGE = 20


def dokument_speichern(
    session: Session,
    inhalt: bytes,
    dateiname: str,
    daten_pfad: str,
    parent_id: int | None = None,
    metadaten: dict | None = None,
) -> tuple[Dokument, bool]:
    """Legt das Dokument an (Dedup per SHA-256). Zweites Element: neu angelegt.

    Die Datei wird nur bei neuen Dokumenten geschrieben. Kein Commit.
    """
    sha = hashlib.sha256(inhalt).hexdigest()
    vorhanden = session.exec(select(Dokument).where(Dokument.sha256 == sha)).first()
    if vorhanden is not None:
        return vorhanden, False
    typ, mime = erkenne_typ(dateiname, inhalt)
    dokument = Dokument(
        sha256=sha,
        dateiname=dateiname,
        typ=typ,
        mime=mime,
        groesse=len(inhalt),
        parent_id=parent_id,
        metadaten=metadaten or {},
    )
    pfad = dokument.dateipfad(daten_pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    session.add(dokument)
    session.flush()
    return dokument, True


def lesen_datei(dokument: Dokument, daten_pfad: str) -> bytes:
    return dokument.dateipfad(daten_pfad).read_bytes()


def _chunks_neu(session: Session, extraktion: TextExtraktion, s: Settings) -> None:
    for position, (start, ende, text) in enumerate(
        chunken(extraktion.text, s.chunk_zeichen, s.chunk_ueberlappung)
    ):
        session.add(
            Chunk(
                textextraktion_id=extraktion.id,
                position=position,
                start=start,
                ende=ende,
                text=text,
            )
        )
    session.flush()


def _aktivieren(
    session: Session, dokument_id: int, ziel: TextExtraktion | None, s: Settings
) -> None:
    alle = session.exec(
        select(TextExtraktion).where(TextExtraktion.dokument_id == dokument_id)
    ).all()
    # Chunks existieren nur für die aktive Extraktion
    for ex in alle:
        if ex.ist_aktiv and ex is not ziel:
            session.execute(delete(Chunk).where(Chunk.textextraktion_id == ex.id))
            ex.ist_aktiv = False
            session.add(ex)
    session.flush()
    if ziel is not None and not ziel.ist_aktiv:
        ziel.ist_aktiv = True
        session.add(ziel)
        session.flush()
        _chunks_neu(session, ziel, s)
    elif ziel is not None:
        # bereits aktiv: Chunks nur anlegen, falls noch keine existieren
        hat = session.exec(
            select(Chunk.id).where(Chunk.textextraktion_id == ziel.id).limit(1)
        ).first()
        if hat is None:
            _chunks_neu(session, ziel, s)


def aktive_extraktion_waehlen(
    session: Session, dokument: Dokument, s: Settings
) -> TextExtraktion | None:
    """Wählt nach Priorität die aktive Extraktion; kein Commit."""
    alle = session.exec(
        select(TextExtraktion).where(TextExtraktion.dokument_id == dokument.id)
    ).all()
    if not alle:
        return None
    nach_methode = {ex.methode: ex for ex in alle}
    ziel = None
    for methode in PRIORITAET:
        ex = nach_methode.get(methode)
        if ex is not None and len(ex.text.strip()) >= MINDESTLAENGE:
            ziel = ex
            break
    if ziel is None:
        ziel = max(alle, key=lambda ex: len(ex.text.strip()))
    _aktivieren(session, dokument.id, ziel, s)
    return ziel


def extraktion_speichern(
    session: Session,
    dokument: Dokument,
    methode: ExtraktionsMethode,
    text: str,
    modell: str | None,
    dauer_ms: int,
    s: Settings,
) -> TextExtraktion:
    """Speichert eine Extraktion, ersetzt eine vorhandene gleicher Methode
    (Chunks/Entitäten/Embeddings kaskadieren per DB) und wählt die aktive neu.

    Kein Commit.
    """
    session.execute(
        delete(TextExtraktion).where(
            TextExtraktion.dokument_id == dokument.id,
            TextExtraktion.methode == methode,
        )
    )
    extraktion = TextExtraktion(
        dokument_id=dokument.id,
        methode=methode,
        text=text,
        modell=modell,
        dauer_ms=dauer_ms,
    )
    session.add(extraktion)
    session.flush()
    aktive_extraktion_waehlen(session, dokument, s)
    return extraktion


def aktiv_setzen(session: Session, extraktion_id: int, s: Settings) -> None:
    """Manueller Wechsel der aktiven Extraktion (GUI/CLI); kein Commit."""
    ziel = session.get(TextExtraktion, extraktion_id)
    if ziel is None:
        raise ValueError(f"Textextraktion {extraktion_id} nicht gefunden")
    _aktivieren(session, ziel.dokument_id, ziel, s)
