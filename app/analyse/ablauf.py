"""LLM-Analysen je Dokument: Zusammenfassung, Klassifikation, Bildbeschreibung."""

import logging
import time
from dataclasses import dataclass

from pydantic import BaseModel
from sqlmodel import Session, select

from app.analyse.kategorien import STANDARD_FRAGE, Kategorie, lade_klassifikation
from app.config import Settings
from app.enums import AnalyseArt, DokumentTyp, LaufStatus
from app.ingest.bild import bild_als_jpeg
from app.ingest.speichern import lesen_datei
from app.models import Analyse, Dokument, Lauf, TextExtraktion
from app.providers.factory import chat_client, classify_client, vision_client
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
    vorhanden: int = 0


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


def klassifizieren(llm: LLMClient, text: str, kategorien: list[Kategorie], frage: str = STANDARD_FRAGE) -> dict:
    liste = "\n".join(f"- {k.name}: {k.beschreibung}" for k in kategorien)
    system = (
        f"{frage}\n"
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


def clef_klassifizieren(client, text: str, kategorien: list[Kategorie], frage: str = STANDARD_FRAGE) -> dict:
    """Gleicher Text (gekuerzt wie beim LLM), gleiche Frage, gleiche Kategorien."""
    antwort = client.klassifiziere(text[:MAX_ZEICHEN], frage, kategorien)
    namen = {k.name.casefold(): k.name for k in kategorien}
    gefunden = namen.get(antwort.kategorie.strip().casefold())
    ergebnis = {
        "kategorie": gefunden or FALLBACK_KATEGORIE,
        "sicherheit": min(1.0, max(0.0, antwort.sicherheit)),
        "wahrscheinlichkeiten": antwort.wahrscheinlichkeiten,
    }
    if gefunden is None:
        ergebnis["roh_kategorie"] = antwort.kategorie
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
    nur_fehlende: bool = True,
) -> AnalyseBilanz:
    """nur_fehlende=True ueberspringt Dokument/Art-Paare mit vorhandener Analyse (ohne neuen Lauf)."""
    abfrage = select(Dokument).order_by(Dokument.id)
    if dokument_id is not None:
        abfrage = abfrage.where(Dokument.id == dokument_id)
    dokumente = session.exec(abfrage).all()
    bilanz = AnalyseBilanz()
    chat = vision = classify = None
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
            provider = s.provider
            if art == AnalyseArt.KLASSIFIKATION_CLEF and not s.clef_aktiv():
                continue  # CLEF ist optional: ohne Cortecs-Schluessel still aus
            if art == AnalyseArt.BILDBESCHREIBUNG:
                if dok.typ != DokumentTyp.BILD:
                    continue
                modell = s.vision_effektiv()[1]
            else:
                modell = s.chat_model
                if art == AnalyseArt.KLASSIFIKATION_CLEF:
                    modell, provider = s.classify_model, "cortecs"
                if not text.strip():
                    if session.exec(
                        select(Lauf.id).where(
                            Lauf.dokument_id == dok_id, Lauf.schritt == schritt,
                            Lauf.status == LaufStatus.UEBERSPRUNGEN,
                        ).limit(1)
                    ).first() is not None:
                        continue  # leerer Text wird nur einmal protokolliert
                    session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=provider, modell=modell,
                                     status=LaufStatus.UEBERSPRUNGEN, fehler="leerer Text"))
                    session.commit()
                    bilanz.uebersprungen += 1
                    continue
            if nur_fehlende and session.exec(
                select(Analyse.id).where(Analyse.dokument_id == dok_id, Analyse.art == art).limit(1)
            ).first() is not None:
                bilanz.vorhanden += 1
                continue
            start = time.monotonic()
            try:
                if art == AnalyseArt.ZUSAMMENFASSUNG:
                    chat = chat or chat_client(s)
                    ergebnis = zusammenfassen(chat, text)
                elif art == AnalyseArt.KLASSIFIKATION_CLEF:
                    classify = classify or classify_client(s)
                    vorgabe = lade_klassifikation(s.kategorien_pfad)
                    ergebnis = clef_klassifizieren(classify, text, vorgabe.kategorien, vorgabe.frage)
                elif art == AnalyseArt.KLASSIFIKATION:
                    chat = chat or chat_client(s)
                    vorgabe = lade_klassifikation(s.kategorien_pfad)
                    ergebnis = klassifizieren(chat, text, vorgabe.kategorien, vorgabe.frage)
                else:
                    vision = vision or vision_client(s)
                    ergebnis = bild_beschreiben(vision, bild_als_jpeg(lesen_datei(dok, s.daten_pfad)))
                for alt in session.exec(
                    select(Analyse).where(Analyse.dokument_id == dok_id, Analyse.art == art)
                ).all():
                    session.delete(alt)
                session.flush()
                session.add(Analyse(dokument_id=dok_id, art=art, modell=modell, ergebnis=ergebnis))
                session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=provider, modell=modell,
                                 dauer_ms=int((time.monotonic() - start) * 1000), status=LaufStatus.ERFOLG))
                session.commit()
                bilanz.erzeugt += 1
            except Exception as e:  # noqa: BLE001 - eine Art darf die anderen nicht stoppen
                logger.warning("Analyse %s fuer Dokument %s fehlgeschlagen: %s", art.value, dok_id, e)
                session.rollback()
                session.add(Lauf(schritt=schritt, dokument_id=dok_id, provider=provider, modell=modell,
                                 dauer_ms=int((time.monotonic() - start) * 1000), status=LaufStatus.FEHLER,
                                 fehler=f"{type(e).__name__}: {e}"[:FEHLER_MAX]))
                session.commit()
                bilanz.fehler += 1
    return bilanz
