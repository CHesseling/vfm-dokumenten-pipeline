"""LLM-Analysen je Dokument: Zusammenfassung, Klassifikation, Bildbeschreibung."""

import logging
import time
from dataclasses import dataclass

from pydantic import BaseModel
from sqlmodel import Session, select

from app.analyse.kategorien import Kategorie, lade_kategorien
from app.config import Settings
from app.enums import AnalyseArt, DokumentTyp, LaufStatus
from app.ingest.bild import bild_als_jpeg
from app.ingest.speichern import lesen_datei
from app.models import Analyse, Dokument, Lauf, TextExtraktion
from app.providers.factory import chat_client, vision_client
from app.providers.llm_client import LLMClient, bild_nachricht

logger = logging.getLogger(__name__)

MAX_ZEICHEN = 12000
FEHLER_MAX = 500
FALLBACK_KATEGORIE = "Sonstiges"

ZUSAMMENFASSUNG_PROMPT = (
    "Fasse den folgenden Text auf Deutsch in 3 bis 5 Sätzen zusammen. Sachlich, ohne Wertung, "
    "nichts hinzuerfinden. Antworte nur mit der Zusammenfassung."
)
TEILE_PROMPT = (
    "Die folgenden Texte sind Zusammenfassungen aufeinanderfolgender Abschnitte eines langen Dokuments. "
    "Fasse sie auf Deutsch zu einer Gesamtzusammenfassung in 3 bis 5 Sätzen zusammen. "
    "Sachlich, nichts hinzuerfinden. Antworte nur mit der Zusammenfassung."
)
BILD_PROMPT = (
    "Beschreibe das Bild auf Deutsch sachlich in wenigen Sätzen: Was ist zu sehen (Motiv, Umgebung, "
    "sichtbarer Text)? Personen nur beschreiben (Anzahl, Kleidung, Tätigkeit), nicht identifizieren "
    "und keine Namen nennen oder raten."
)


class KlassifikationSchema(BaseModel):
    kategorie: str
    begruendung: str
    sicherheit: float


@dataclass
class AnalyseBilanz:
    dokumente: int = 0
    erzeugt: int = 0
    fehler: int = 0
    uebersprungen: int = 0


def _frage(system: str, text: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


MAX_REDUKTIONSEBENEN = 3


def zusammenfassen(llm: LLMClient, text: str) -> dict:
    if len(text) <= MAX_ZEICHEN:
        return {"text": llm.chat_text(_frage(ZUSAMMENFASSUNG_PROMPT, text))}
    teile = [
        llm.chat_text(_frage(ZUSAMMENFASSUNG_PROMPT, text[i : i + MAX_ZEICHEN]))
        for i in range(0, len(text), MAX_ZEICHEN)
    ]
    # Hierarchisch reduzieren (hoechstens MAX_REDUKTIONSEBENEN Ebenen), bis alles in einen Aufruf passt.
    for _ in range(MAX_REDUKTIONSEBENEN):
        eintraege = [f"Abschnitt {n}: {t}" for n, t in enumerate(teile, 1)]
        if len("\n\n".join(eintraege)) <= MAX_ZEICHEN or len(teile) == 1:
            break
        gruppen, aktuell = [], []
        for e in eintraege:
            if aktuell and len("\n\n".join(aktuell + [e])) > MAX_ZEICHEN:
                gruppen.append(aktuell)
                aktuell = []
            aktuell.append(e)
        gruppen.append(aktuell)
        if len(gruppen) >= len(teile):  # keine Verdichtung moeglich
            break
        teile = [llm.chat_text(_frage(TEILE_PROMPT, "\n\n".join(g)[:MAX_ZEICHEN])) for g in gruppen]
    eintraege = [f"Abschnitt {n}: {t}" for n, t in enumerate(teile, 1)]
    gesamt = "\n\n".join(eintraege)
    ergebnis = {"text": llm.chat_text(_frage(TEILE_PROMPT, gesamt[:MAX_ZEICHEN]))}
    if len(gesamt) > MAX_ZEICHEN:
        ergebnis["gekuerzt"] = True
    return ergebnis


def klassifizieren(llm: LLMClient, text: str, kategorien: list[Kategorie]) -> dict:
    liste = "\n".join(f"- {k.name}: {k.beschreibung}" for k in kategorien)
    system = (
        "Ordne das Dokument genau einer der folgenden Kategorien zu:\n"
        f"{liste}\n\n"
        "Antworte als JSON mit den Feldern kategorie (exakt einer der Namen oben), "
        "begruendung (ein Satz auf Deutsch) und sicherheit (Zahl von 0 bis 1)."
    )
    roh = llm.chat_json(_frage(system, text[:MAX_ZEICHEN]), KlassifikationSchema)
    namen = {k.name.casefold(): k.name for k in kategorien}
    gefunden = namen.get(roh.kategorie.strip().casefold())
    ergebnis = {
        "kategorie": gefunden or FALLBACK_KATEGORIE,
        "begruendung": roh.begruendung,
        "sicherheit": min(1.0, max(0.0, roh.sicherheit)),
    }
    if gefunden is None:
        ergebnis["roh_kategorie"] = roh.kategorie
    return ergebnis


def bild_beschreiben(vision: LLMClient, bild_jpeg: bytes) -> dict:
    return {"text": vision.chat_text([bild_nachricht(BILD_PROMPT, [(bild_jpeg, "image/jpeg")])])}


def analyse_ausfuehren(
    session: Session,
    s: Settings,
    arten: set[AnalyseArt],
    dokument_id: int | None = None,
    bei_dokument=None,
    soll_abbrechen=None,
) -> AnalyseBilanz:
    abfrage = select(Dokument).order_by(Dokument.id)
    if dokument_id is not None:
        abfrage = abfrage.where(Dokument.id == dokument_id)
    dokumente = session.exec(abfrage).all()
    bilanz = AnalyseBilanz()
    chat = vision = None
    for nr, dok in enumerate(dokumente, 1):
        if soll_abbrechen is not None and soll_abbrechen():
            break
        dok_id = dok.id
        if bei_dokument is not None:
            bei_dokument(nr, len(dokumente), dok.dateiname)
        bilanz.dokumente += 1
        aktiv = session.exec(
            select(TextExtraktion).where(TextExtraktion.dokument_id == dok_id, TextExtraktion.ist_aktiv.is_(True))
        ).first()
        text = aktiv.text if aktiv else ""
        for art in sorted(arten, key=lambda a: a.value):
            schritt = f"analyse:{art.value}"
            if art == AnalyseArt.BILDBESCHREIBUNG:
                if dok.typ != DokumentTyp.BILD:
                    continue
                modell = s.vision_effektiv()[1]
            else:
                modell = s.chat_model
                if not text.strip():
                    session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=s.provider, modell=modell,
                                     status=LaufStatus.UEBERSPRUNGEN, fehler="leerer Text"))
                    session.commit()
                    bilanz.uebersprungen += 1
                    continue
            start = time.monotonic()
            try:
                if art == AnalyseArt.ZUSAMMENFASSUNG:
                    chat = chat or chat_client(s)
                    ergebnis = zusammenfassen(chat, text)
                elif art == AnalyseArt.KLASSIFIKATION:
                    chat = chat or chat_client(s)
                    ergebnis = klassifizieren(chat, text, lade_kategorien(s.kategorien_pfad))
                else:
                    vision = vision or vision_client(s)
                    ergebnis = bild_beschreiben(vision, bild_als_jpeg(lesen_datei(dok, s.daten_pfad)))
                for alt in session.exec(
                    select(Analyse).where(Analyse.dokument_id == dok_id, Analyse.art == art)
                ).all():
                    session.delete(alt)
                session.flush()
                session.add(Analyse(dokument_id=dok_id, art=art, modell=modell, ergebnis=ergebnis))
                session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=s.provider, modell=modell,
                                 dauer_ms=int((time.monotonic() - start) * 1000), status=LaufStatus.ERFOLG))
                session.commit()
                bilanz.erzeugt += 1
            except Exception as e:  # noqa: BLE001 - eine Art darf die anderen nicht stoppen
                logger.warning("Analyse %s fuer Dokument %s fehlgeschlagen: %s", art.value, dok_id, e)
                session.rollback()
                session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=s.provider, modell=modell,
                                 dauer_ms=int((time.monotonic() - start) * 1000), status=LaufStatus.FEHLER,
                                 fehler=f"{type(e).__name__}: {e}"[:FEHLER_MAX]))
                session.commit()
                bilanz.fehler += 1
    return bilanz
