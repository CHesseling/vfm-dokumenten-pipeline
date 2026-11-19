"""Ingest-Ablauf: Dateien und Ordner einlesen, Methoden je Dateityp ausführen.

Nach jeder Datei wird committed, damit ein späterer Fehler frühere Dateien und
``Lauf``-Zeilen nicht verliert.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from app.config import Settings
from app.enums import DokumentTyp, ExtraktionsMethode, LaufStatus
from app.ingest.audio import audio_transkribieren
from app.ingest.bild import bild_metadaten, bild_ocr
from app.ingest.dateitypen import erkenne_typ
from app.ingest.eml import EmlInhalt, eml_lesen
from app.ingest.office import office_docling
from app.ingest.pdf import pdf_docling, pdf_schnell, pdf_vision
from app.ingest.speichern import dokument_speichern, extraktion_speichern
from app.ingest.text import text_lesen
from app.models import Dokument, Lauf, TextExtraktion
from app.providers.factory import transkribierer, vision_client
from app.providers.llm_client import LLMClient
from app.providers.transcribe import Transkribierer

logger = logging.getLogger(__name__)

MINDEST_TEXT_SCHNELL = 200
FEHLER_MAX = 500


@dataclass
class IngestClients:
    vision: LLMClient
    transkribierer: Transkribierer


@dataclass
class IngestBilanz:
    neu: int = 0
    bekannt: int = 0
    fehler: int = 0


@dataclass
class IngestErgebnis:
    dokument: Dokument
    neu: bool
    # Alle Extraktionsmethoden dieser Datei (bzw. eines Anhangs) endeten mit FEHLER.
    fehlgeschlagen: bool = False


def ingest_clients(s: Settings) -> IngestClients:
    """Baut die Clients; Modelle werden erst bei Erstbenutzung geladen."""
    return IngestClients(vision=vision_client(s), transkribierer=transkribierer(s))


def _fehlertext(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:FEHLER_MAX]


def _lauf_schreiben(
    session: Session,
    dokument_id: int,
    methode: str,
    s: Settings,
    modell: str | None,
    dauer_ms: int,
    status: LaufStatus,
    fehler: str | None = None,
) -> None:
    if session.in_transaction() and not session.is_active:
        session.rollback()
    session.add(
        Lauf(
            schritt=f"extraktion:{methode}",
            dokument_id=dokument_id,
            provider=s.provider,
            modell=modell,
            dauer_ms=dauer_ms,
            status=status,
            fehler=fehler,
        )
    )
    session.commit()


def _methode_ausfuehren(
    session: Session,
    dokument: Dokument,
    methode: ExtraktionsMethode,
    s: Settings,
    modell: str | None,
    funktion: Callable[[], str],
) -> str | None:
    """Führt eine Methode aus, speichert Extraktion + Lauf; Fehler werden zum Lauf(FEHLER)."""
    dokument_id = dokument.id
    start = time.monotonic()
    try:
        text = funktion()
        dauer = int((time.monotonic() - start) * 1000)
        extraktion_speichern(session, dokument, methode, text, modell, dauer, s)
        _lauf_schreiben(session, dokument_id, methode.value, s, modell, dauer, LaufStatus.ERFOLG)
        return text
    except Exception as e:  # noqa: BLE001 - ein Fehler darf die anderen Methoden nicht stoppen
        dauer = int((time.monotonic() - start) * 1000)
        logger.warning("Methode %s für Dokument %s fehlgeschlagen: %s", methode.value, dokument_id, e)
        session.rollback()
        _lauf_schreiben(
            session, dokument_id, methode.value, s, modell, dauer, LaufStatus.FEHLER, _fehlertext(e)
        )
        return None


def _letzte_lauf_id(session: Session) -> int:
    return session.exec(select(func.max(Lauf.id))).one() or 0


def _nur_fehler(session: Session, dokument_id: int, ab_lauf_id: int) -> bool:
    """True, wenn seit ab_lauf_id Extraktionslaeufe liefen und keiner erfolgreich war."""
    stati = session.exec(
        select(Lauf.status).where(
            Lauf.dokument_id == dokument_id, Lauf.id > ab_lauf_id, Lauf.schritt.like("extraktion:%")
        )
    ).all()
    return LaufStatus.FEHLER in stati and LaufStatus.ERFOLG not in stati


def _vorhandene_methoden(session: Session, dokument_id: int) -> set[ExtraktionsMethode]:
    return set(
        session.exec(
            select(TextExtraktion.methode).where(TextExtraktion.dokument_id == dokument_id)
        ).all()
    )


def _pdf_methoden(methoden: set[str] | None) -> set[str]:
    if methoden is None:
        return {"schnell"}
    if "alle" in methoden:
        return {"schnell", "docling", "vision"}
    return methoden & {"schnell", "docling", "vision"} or {"schnell"}


def _verarbeite_pdf(session, dokument, inhalt, s, clients, methoden, vorhanden) -> None:
    gewuenscht = _pdf_methoden(methoden)
    schnell_text: str | None = None
    if "schnell" in gewuenscht and ExtraktionsMethode.SCHNELL not in vorhanden:
        schnell_text = _methode_ausfuehren(
            session, dokument, ExtraktionsMethode.SCHNELL, s, None, lambda: pdf_schnell(inhalt)
        )
        if (
            methoden is None
            and schnell_text is not None
            and len(schnell_text.strip()) < MINDEST_TEXT_SCHNELL
        ):
            gewuenscht = gewuenscht | {"docling"}
    if "docling" in gewuenscht and ExtraktionsMethode.DOCLING not in vorhanden:
        _methode_ausfuehren(
            session,
            dokument,
            ExtraktionsMethode.DOCLING,
            s,
            "docling",
            lambda: pdf_docling(inhalt, s.docling_artifacts_pfad),
        )
    if "vision" in gewuenscht and ExtraktionsMethode.VISION not in vorhanden:
        _methode_ausfuehren(
            session,
            dokument,
            ExtraktionsMethode.VISION,
            s,
            clients.vision.model,
            lambda: pdf_vision(inhalt, clients.vision),
        )


def _ingest(
    session: Session,
    inhalt: bytes,
    dateiname: str,
    s: Settings,
    clients: IngestClients,
    methoden: set[str] | None,
    parent_id: int | None,
) -> IngestErgebnis:
    ab_lauf_id = _letzte_lauf_id(session)
    anhang_fehler = False
    eml: EmlInhalt | None = None
    metadaten: dict = {}
    typ_vorab, _ = erkenne_typ(dateiname, inhalt)
    eml_fehler: Exception | None = None
    if typ_vorab == DokumentTyp.EML:
        try:
            eml = eml_lesen(inhalt)
            metadaten = eml.metadaten
        except Exception as e:  # noqa: BLE001
            eml_fehler = e
    elif typ_vorab == DokumentTyp.BILD:
        try:
            metadaten = bild_metadaten(inhalt)
        except Exception as e:  # noqa: BLE001
            logger.warning("Bild-Metadaten nicht lesbar (%s): %s", dateiname, e)

    dokument, neu = dokument_speichern(
        session, inhalt, dateiname, s.daten_pfad, parent_id=parent_id, metadaten=metadaten
    )
    session.commit()
    dokument_id = dokument.id
    typ = dokument.typ
    vorhanden = _vorhandene_methoden(session, dokument_id)

    if typ == DokumentTyp.PDF:
        _verarbeite_pdf(session, dokument, inhalt, s, clients, methoden, vorhanden)
    elif typ == DokumentTyp.EML:
        if eml_fehler is not None and ExtraktionsMethode.EML not in vorhanden:
            _lauf_schreiben(
                session, dokument_id, "eml", s, None, 0, LaufStatus.FEHLER, _fehlertext(eml_fehler)
            )
        elif eml is not None:
            if ExtraktionsMethode.EML not in vorhanden:
                _methode_ausfuehren(session, dokument, ExtraktionsMethode.EML, s, None, lambda: eml.text)
            for name, anhang in eml.anhaenge:
                try:
                    anhang_fehler |= _ingest(
                        session, anhang, name, s, clients, methoden, dokument_id
                    ).fehlgeschlagen
                except Exception as e:  # noqa: BLE001
                    session.rollback()
                    anhang_fehler = True
                    logger.warning("Anhang %s nicht verarbeitbar: %s", name, e)
                    _lauf_schreiben(
                        session, dokument_id, "anhang", s, None, 0, LaufStatus.FEHLER,
                        _fehlertext(e),
                    )
    elif typ in (DokumentTyp.AUDIO, DokumentTyp.VIDEO):
        if ExtraktionsMethode.WHISPER not in vorhanden:
            _methode_ausfuehren(
                session,
                dokument,
                ExtraktionsMethode.WHISPER,
                s,
                getattr(clients.transkribierer, "model", None),
                lambda: audio_transkribieren(inhalt, dateiname, clients.transkribierer),
            )
    elif typ == DokumentTyp.BILD:
        if ExtraktionsMethode.VISION not in vorhanden:
            _methode_ausfuehren(
                session,
                dokument,
                ExtraktionsMethode.VISION,
                s,
                clients.vision.model,
                lambda: bild_ocr(inhalt, clients.vision),
            )
    elif typ == DokumentTyp.OFFICE:
        if ExtraktionsMethode.DOCLING not in vorhanden:
            _methode_ausfuehren(
                session, dokument, ExtraktionsMethode.DOCLING, s, "docling",
                lambda: office_docling(inhalt, dateiname, s.docling_artifacts_pfad),
            )
    elif typ == DokumentTyp.TEXT:
        if ExtraktionsMethode.TEXT not in vorhanden:
            _methode_ausfuehren(
                session, dokument, ExtraktionsMethode.TEXT, s, None, lambda: text_lesen(inhalt)
            )
    elif neu:
        _lauf_schreiben(
            session, dokument_id, "extraktion", s, None, 0, LaufStatus.UEBERSPRUNGEN,
            "Dateityp nicht unterstützt",
        )
    return IngestErgebnis(dokument, neu, anhang_fehler or _nur_fehler(session, dokument_id, ab_lauf_id))


def ingest_datei_mit_ergebnis(
    session: Session,
    inhalt: bytes,
    dateiname: str,
    s: Settings,
    clients: IngestClients,
    methoden: set[str] | None = None,
    parent_id: int | None = None,
) -> IngestErgebnis:
    return _ingest(session, inhalt, dateiname, s, clients, methoden, parent_id)


def ingest_datei(
    session: Session,
    inhalt: bytes,
    dateiname: str,
    s: Settings,
    clients: IngestClients,
    methoden: set[str] | None = None,
    parent_id: int | None = None,
) -> Dokument:
    return _ingest(session, inhalt, dateiname, s, clients, methoden, parent_id).dokument


def dateien_finden(pfad: Path) -> list[Path]:
    pfad = Path(pfad)
    if pfad.is_file():
        return [pfad]
    gefunden = []
    for p in pfad.rglob("*"):
        if not p.is_file():
            continue
        teile = p.relative_to(pfad).parts
        if any(t.startswith(".") for t in teile) or "processed" in teile[:-1]:
            continue
        gefunden.append(p)
    return sorted(gefunden)


def ingest_ordner(
    session: Session,
    pfad: Path,
    s: Settings,
    clients: IngestClients,
    methoden: set[str] | None = None,
    bei_datei: Callable[[int, int, str], None] | None = None,
    soll_abbrechen: Callable[[], bool] | None = None,
) -> IngestBilanz:
    dateien = dateien_finden(pfad)
    bilanz = IngestBilanz()
    for nr, datei in enumerate(dateien, start=1):
        if soll_abbrechen is not None and soll_abbrechen():
            break
        if bei_datei is not None:
            bei_datei(nr, len(dateien), datei.name)
        try:
            ergebnis = _ingest(session, datei.read_bytes(), datei.name, s, clients, methoden, None)
            session.commit()
            if ergebnis.fehlgeschlagen:
                bilanz.fehler += 1
            elif ergebnis.neu:
                bilanz.neu += 1
            else:
                bilanz.bekannt += 1
        except Exception as e:  # noqa: BLE001 - eine kaputte Datei stoppt nicht den Ordner
            session.rollback()
            logger.error("Datei %s nicht verarbeitbar: %s", datei, e)
            bilanz.fehler += 1
    return bilanz
