"""Status-Seite: Provider-Konfiguration, Verbindungspruefung, Zaehlerstaende, Hintergrund-Laeufe."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.analyse.ablauf import analyse_ausfuehren
from app.config import Settings, get_settings
from app.db import get_session
from app.embed.index import embed_ausfuehren
from app.enums import AnalyseArt, DokumentTyp, NerMethode
from app.ner.ablauf import ner_ausfuehren
from app.providers.check import pruefe_rollen
from app.providers.factory import embedding_client
from app.providers.url import ohne_zugangsdaten
from app.statistik import STUFEN, zaehlerstaende
from app.web.routes_upload import lauf_starten
from app.web.vorlagen import templates

router = APIRouter()

KEIN_WERT = "–"
SPALTEN = ("Dokumente", "mit aktivem Text", "mit Entitäten", "mit Embeddings", "mit Analyse")


def maskiere_key(key: str | None) -> str:
    """Nur die ersten 4 Zeichen und ein Auslassungszeichen - nie der volle Schluessel."""
    return f"{key[:4]}…" if key else KEIN_WERT


def rollen_konfiguration(s: Settings) -> list[dict]:
    vision_url, vision_modell, vision_key = s.vision_effektiv()
    zeilen = [
        ("chat", "api", s.chat_model, s.chat_base_url, s.api_key_fuer("chat")),
        ("vision", "api", vision_modell, vision_url, vision_key),
        ("embed", "api", s.embed_model, s.embed_base_url, s.api_key_fuer("embed")),
        ("rerank", s.rerank_backend, s.rerank_model if s.rerank_backend != "none" else None,
         s.rerank_base_url if s.rerank_backend == "api" else None, s.api_key_fuer("rerank")),
        ("transcribe", s.transcribe_backend, s.transcribe_model,
         s.transcribe_base_url if s.transcribe_backend == "api" else None, s.api_key_fuer("transcribe")),
    ]
    return [
        {"rolle": r, "provider": s.provider, "backend": b, "modell": m or KEIN_WERT, "url": ohne_zugangsdaten(u) or KEIN_WERT,
         "key": maskiere_key(k)}
        for r, b, m, u, k in zeilen
    ]


def _seite(request: Request, session: Session, s: Settings, check=None):
    zahlen = zaehlerstaende(session, s)
    typen = [
        (t.value, [zahlen[stufe].get(t, 0) for stufe in STUFEN]) for t in DokumentTyp
    ]
    return templates.TemplateResponse(
        request,
        "status.html",
        {"rollen": rollen_konfiguration(s), "provider": s.provider, "spalten": SPALTEN, "typen": typen,
         "check": check},
    )


@router.get("/status")
def status_seite(request: Request, session: Session = Depends(get_session), s: Settings = Depends(get_settings)):
    return _seite(request, session, s)


@router.post("/status/check")
def verbindung_pruefen(
    request: Request, session: Session = Depends(get_session), s: Settings = Depends(get_settings)
):
    return _seite(request, session, s, check=pruefe_rollen(s))


@router.post("/status/ner")
def ner_fuer_alle(s: Settings = Depends(get_settings)):
    lauf_starten(
        "ner",
        lambda session, bei, abbruch: ner_ausfuehren(
            session, s, {NerMethode.GLINER, NerMethode.MUSTER}, bei_dokument=bei, soll_abbrechen=abbruch
        ),
        s,
    )
    return RedirectResponse(url="/laeufe/ner", status_code=303)


@router.post("/status/embed")
def embeddings_erzeugen(s: Settings = Depends(get_settings)):
    lauf_starten(
        "embed",
        lambda session, bei, abbruch: embed_ausfuehren(
            session, embedding_client(s), bei_fortschritt=bei, soll_abbrechen=abbruch, provider=s.provider
        ),
        s,
    )
    return RedirectResponse(url="/laeufe/embed", status_code=303)


@router.post("/status/analyse")
def analyse_fuer_alle(s: Settings = Depends(get_settings)):
    lauf_starten(
        "analyse",
        lambda session, bei, abbruch: analyse_ausfuehren(
            session, s, set(AnalyseArt), bei_dokument=bei, soll_abbrechen=abbruch
        ),
        s,
    )
    return RedirectResponse(url="/laeufe/analyse", status_code=303)
