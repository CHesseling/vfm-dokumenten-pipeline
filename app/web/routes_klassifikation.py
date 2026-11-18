from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from app.analyse.kategorien import lade_klassifikation
from app.analyse.vergleich import klassifikation_vergleich
from app.config import Settings, get_settings
from app.db import get_session
from app.web.vorlagen import templates

router = APIRouter()


@router.get("/klassifikation")
def klassifikation_seite(
    request: Request,
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    try:
        vorgabe, vorgabe_fehler = lade_klassifikation(s.kategorien_pfad), None
    except ValueError as fehler:  # kaputte YAML-Datei: Meldung statt 500
        vorgabe, vorgabe_fehler = None, str(fehler)
    return templates.TemplateResponse(
        request,
        "klassifikation.html",
        {"vorgabe": vorgabe, "vorgabe_fehler": vorgabe_fehler, "zeilen": klassifikation_vergleich(session),
         "clef_aktiv": s.clef_aktiv(), "chat_model": s.chat_model, "classify_model": s.classify_model},
    )
