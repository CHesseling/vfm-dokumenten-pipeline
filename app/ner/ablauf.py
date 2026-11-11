"""NER-Ablauf: Methoden je aktiver Textextraktion ausfuehren, speichern, vergleichen."""

import logging
import re
import time
from dataclasses import dataclass, field, replace

from sqlmodel import Session, select

from app.config import Settings
from app.enums import LaufStatus, NerMethode
from app.models import Dokument, Entitaet, Lauf, TextExtraktion
from app.ner.gliner import GlinerNer
from app.ner.llm_ner import llm_ner
from app.ner.muster import finde_muster, normalisiere
from app.ner.treffer import LABELS, Treffer
from app.providers.factory import chat_client

logger = logging.getLogger(__name__)
FEHLER_MAX = 500


@dataclass
class NerBilanz:
    dokumente: int = 0
    entitaeten: int = 0
    fehler: int = 0
    uebersprungen: int = 0
    vorhanden: int = 0


@dataclass(frozen=True)
class VergleichZeile:
    label: str
    text_normalisiert: str
    methoden: set[str] = field(default_factory=set)


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _finde(methode: NerMethode, s: Settings, text: str, labels: list[str], statistik: dict) -> list[Treffer]:
    if methode == NerMethode.MUSTER:
        return [t for t in finde_muster(text) if t.label in labels]
    if methode == NerMethode.GLINER:
        treffer = GlinerNer(s.gliner_model).finde(text, labels)
        return [replace(t, normalisiert=normalisiere(t.label, t.text)) for t in treffer]
    treffer = llm_ner(chat_client(s), text, labels, statistik)
    return [replace(t, normalisiert=normalisiere(t.label, t.text)) for t in treffer]


def _modell(methode: NerMethode, s: Settings) -> str | None:
    return {NerMethode.GLINER: s.gliner_model, NerMethode.LLM: s.chat_model}.get(methode)


def _schon_protokolliert(session: Session, dokument_id: int, schritt: str, status: LaufStatus) -> list[Lauf]:
    return session.exec(
        select(Lauf).where(Lauf.dokument_id == dokument_id, Lauf.schritt == schritt, Lauf.status == status)
    ).all()


def _ner_vorhanden(session: Session, ex_id: int, dok_id: int, methode: NerMethode, schritt: str) -> bool:
    """Gibt es fuer diese Extraktion und Methode schon Entitaeten oder einen erfolgreichen Lauf?"""
    if session.exec(
        select(Entitaet.id).where(Entitaet.textextraktion_id == ex_id, Entitaet.methode == methode).limit(1)
    ).first() is not None:
        return True
    return any(
        (l.roh_output or {}).get("extraktion_id") == ex_id
        for l in _schon_protokolliert(session, dok_id, schritt, LaufStatus.ERFOLG)
    )


def ner_ausfuehren(
    session: Session,
    s: Settings,
    methoden: set[NerMethode],
    dokument_id: int | None = None,
    labels: list[str] | None = None,
    bei_dokument=None,
    soll_abbrechen=None,
    nur_fehlende: bool = True,
) -> NerBilanz:
    """nur_fehlende=True ueberspringt (Extraktion, Methode)-Paare mit vorhandenem Ergebnis."""
    labels = list(labels or LABELS)
    abfrage = select(TextExtraktion).where(TextExtraktion.ist_aktiv.is_(True))
    if dokument_id is not None:
        abfrage = abfrage.where(TextExtraktion.dokument_id == dokument_id)
    extraktionen = session.exec(abfrage.order_by(TextExtraktion.dokument_id)).all()
    bilanz = NerBilanz()
    for nr, ex in enumerate(extraktionen, 1):
        if soll_abbrechen is not None and soll_abbrechen():
            break
        ex_id, dok_id, text = ex.id, ex.dokument_id, ex.text
        if bei_dokument is not None:
            dok = session.get(Dokument, dok_id)
            bei_dokument(nr, len(extraktionen), dok.dateiname if dok else str(dok_id))
        bilanz.dokumente += 1
        for methode in sorted(methoden, key=lambda m: m.value):
            schritt = f"ner:{methode.value}"
            modell = _modell(methode, s)
            if not text.strip():
                if _schon_protokolliert(session, dok_id, schritt, LaufStatus.UEBERSPRUNGEN):
                    continue  # leerer Text wird nur einmal protokolliert
                session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=s.provider, modell=modell,
                                 status=LaufStatus.UEBERSPRUNGEN, fehler="leerer Text"))
                session.commit()
                bilanz.uebersprungen += 1
                continue
            if nur_fehlende and _ner_vorhanden(session, ex_id, dok_id, methode, schritt):
                bilanz.vorhanden += 1
                continue
            start = time.monotonic()
            statistik: dict = {}
            try:
                treffer = _finde(methode, s, text, labels, statistik)
                for alt in session.exec(
                    select(Entitaet).where(Entitaet.textextraktion_id == ex_id, Entitaet.methode == methode)
                ).all():
                    session.delete(alt)
                session.flush()
                for t in treffer:
                    session.add(Entitaet(textextraktion_id=ex_id, methode=methode, label=t.label, text=t.text,
                                         normalisiert=t.normalisiert, start=t.start, ende=t.ende, score=t.score))
                session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=s.provider, modell=modell,
                                 dauer_ms=int((time.monotonic() - start) * 1000), status=LaufStatus.ERFOLG,
                                 roh_output={**statistik, "extraktion_id": ex_id}))
                session.commit()
                bilanz.entitaeten += len(treffer)
            except Exception as e:  # noqa: BLE001 - eine Methode darf die anderen nicht stoppen
                logger.warning("NER %s fuer Dokument %s fehlgeschlagen: %s", methode.value, dok_id, e)
                session.rollback()
                session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=s.provider, modell=modell,
                                 dauer_ms=int((time.monotonic() - start) * 1000), status=LaufStatus.FEHLER,
                                 fehler=f"{type(e).__name__}: {e}"[:FEHLER_MAX]))
                session.commit()
                bilanz.fehler += 1
    return bilanz


def vergleich(session: Session, extraktion_id: int) -> list[VergleichZeile]:
    zeilen: dict[tuple[str, str], set[str]] = {}
    anzeige: dict[tuple[str, str], str] = {}
    for e in session.exec(select(Entitaet).where(Entitaet.textextraktion_id == extraktion_id)).all():
        schluessel = (e.label, _normal(e.text))
        zeilen.setdefault(schluessel, set()).add(e.methode.value)
        anzeige.setdefault(schluessel, schluessel[1])
    return [VergleichZeile(l, t, m) for (l, t), m in sorted(zeilen.items())]
