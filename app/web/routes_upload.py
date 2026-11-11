import logging
import threading
import uuid
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app import progress
from app.config import Settings, get_settings
from app.db import get_engine
from app.ingest.ablauf import ingest_clients, ingest_datei_mit_ergebnis, ingest_ordner
from app.web.vorlagen import templates

logger = logging.getLogger(__name__)

router = APIRouter()

ORDNER_SCHLUESSEL = "ordner"
METHODEN = ("schnell", "docling", "vision", "alle")
VERLAUF_ZEILEN = 50

# Nur ein Ordner-Import gleichzeitig (Button doppelt geklickt, mehrere Tabs).
_ordner_lock = threading.Lock()


def _starte_thread(ziel, *args) -> None:
    threading.Thread(target=ziel, args=args, daemon=True).start()


# Schluessel der gerade laufenden Hintergrundlaeufe (lauf_starten): pro Schluessel nur einer.
_laeufe_aktiv: set[str] = set()
_laeufe_lock = threading.Lock()


def _lauf_im_hintergrund(schluessel: str, funktion: Callable, s: Settings) -> None:
    def bei_fortschritt(nr: int, gesamt: int, name: str | None = None) -> None:
        if name is not None:  # nr = Nummer des gerade begonnenen Elements
            progress.aktualisieren(schluessel, f"Verarbeite {name} ({nr}/{gesamt})")
            progress.zaehler_setzen(schluessel, nr - 1, gesamt, 0)
        else:  # nr = bereits erledigte Elemente
            progress.aktualisieren(schluessel, f"{nr}/{gesamt}")
            progress.zaehler_setzen(schluessel, nr, gesamt, 0)

    try:
        with Session(get_engine(s.database_url)) as session:
            bilanz = funktion(session, bei_fortschritt, lambda: progress.abbruch_angefordert(schluessel))
        fehler = getattr(bilanz, "fehler", 0)
        fehler = fehler if isinstance(fehler, int) else 0
        status = progress.lesen(schluessel)
        if status is not None and status.gesamt:
            progress.zaehler_setzen(schluessel, status.gesamt, status.gesamt, max(fehler, status.fehlgeschlagen))
        if fehler:
            progress.aktualisieren(
                schluessel, f"Fertig – {fehler} Fehler, Details in der Läufe-Tabelle der Dokumente"
            )
        progress.abschliessen(schluessel)
    except Exception as e:  # noqa: BLE001
        logger.exception("Lauf %s fehlgeschlagen", schluessel)
        progress.abschliessen(schluessel, fehler=str(e))
    finally:
        with _laeufe_lock:
            _laeufe_aktiv.discard(schluessel)


def lauf_starten(
    schluessel: str,
    funktion: Callable[[Session, Callable, Callable], object],
    s: Settings | None = None,
) -> bool:
    """Startet `funktion(session, bei_fortschritt, soll_abbrechen)` in einem Hintergrund-Thread mit
    eigener Session. False, wenn unter diesem Schluessel schon ein Lauf aktiv ist."""
    with _laeufe_lock:
        if schluessel in _laeufe_aktiv:
            return False
        _laeufe_aktiv.add(schluessel)
    progress.starten(schluessel)
    try:
        _starte_thread(_lauf_im_hintergrund, schluessel, funktion, s or get_settings())
    except Exception as e:
        progress.abschliessen(schluessel, fehler=str(e))
        with _laeufe_lock:
            _laeufe_aktiv.discard(schluessel)
        raise
    return True


def _methoden(methode: str) -> set[str] | None:
    if methode not in METHODEN:
        raise HTTPException(status_code=400, detail="Unbekannte Methode")
    return None if methode == "schnell" else {methode}


def _upload_im_hintergrund(
    schluessel: str, dateien: list[tuple[str, bytes]], methoden: set[str] | None, s: Settings
) -> None:
    try:
        with Session(get_engine(s.database_url)) as session:
            clients = ingest_clients(s)
            fehler = 0
            for nr, (name, inhalt) in enumerate(dateien, start=1):
                if progress.abbruch_angefordert(schluessel):
                    progress.aktualisieren(
                        schluessel, f"Abgebrochen nach {nr - 1} von {len(dateien)} Dateien"
                    )
                    break
                progress.aktualisieren(schluessel, f"Verarbeite {name} ({nr}/{len(dateien)})")
                try:
                    ergebnis = ingest_datei_mit_ergebnis(session, inhalt, name, s, clients, methoden=methoden)
                    if ergebnis.fehlgeschlagen:
                        fehler += 1
                except Exception as e:  # noqa: BLE001 - eine Datei stoppt nicht die übrigen
                    session.rollback()
                    logger.exception("Upload %s fehlgeschlagen", name)
                    fehler += 1
                progress.zaehler_setzen(schluessel, nr, len(dateien), fehler)
        if fehler:
            progress.aktualisieren(
                schluessel, f"Fertig – {fehler} Fehler, Details in der Läufe-Tabelle der Dokumente"
            )
        progress.abschliessen(schluessel)
    except Exception as e:  # noqa: BLE001
        logger.exception("Upload-Lauf fehlgeschlagen")
        progress.abschliessen(schluessel, fehler=str(e))


def _ordner_im_hintergrund(methoden: set[str] | None, s: Settings) -> None:
    """Läuft mit gehaltenem _ordner_lock; gibt ihn am Ende frei."""
    try:
        with Session(get_engine(s.database_url)) as session:
            fehler = 0

            def bei_datei(nr: int, gesamt: int, name: str) -> None:
                progress.aktualisieren(ORDNER_SCHLUESSEL, f"Verarbeite {name} ({nr}/{gesamt})")
                progress.zaehler_setzen(ORDNER_SCHLUESSEL, nr - 1, gesamt, fehler)

            bilanz = ingest_ordner(
                session,
                Path(s.material_pfad),
                s,
                ingest_clients(s),
                methoden=methoden,
                bei_datei=bei_datei,
                soll_abbrechen=lambda: progress.abbruch_angefordert(ORDNER_SCHLUESSEL),
            )
            status = progress.lesen(ORDNER_SCHLUESSEL)
            gesamt = bilanz.neu + bilanz.bekannt + bilanz.fehler
            progress.zaehler_setzen(ORDNER_SCHLUESSEL, gesamt, status.gesamt if status else gesamt, bilanz.fehler)
            progress.aktualisieren(
                ORDNER_SCHLUESSEL,
                f"Fertig: {bilanz.neu} neu, {bilanz.bekannt} bekannt, {bilanz.fehler} Fehler",
            )
        progress.abschliessen(ORDNER_SCHLUESSEL)
    except Exception as e:  # noqa: BLE001
        logger.exception("Ordner-Import fehlgeschlagen")
        progress.abschliessen(ORDNER_SCHLUESSEL, fehler=str(e))
    finally:
        _ordner_lock.release()


@router.get("/upload")
def upload_formular(request: Request, s: Settings = Depends(get_settings)):
    status = progress.lesen(ORDNER_SCHLUESSEL)
    return templates.TemplateResponse(
        request,
        "upload.html",
        {"material_pfad": s.material_pfad, "ordner_status": status},
    )


@router.post("/upload")
def upload_verarbeiten(
    datei: list[UploadFile] = File(...),
    methode: str = Form("schnell"),
    s: Settings = Depends(get_settings),
):
    methoden = _methoden(methode)
    dateien = [(f.filename or "upload", f.file.read()) for f in datei]
    schluessel = f"upload:{uuid.uuid4().hex}"
    progress.starten(schluessel)
    progress.zaehler_setzen(schluessel, 0, len(dateien), 0)
    _starte_thread(_upload_im_hintergrund, schluessel, dateien, methoden, s)
    return RedirectResponse(url=f"/laeufe/{schluessel}", status_code=303)


@router.post("/upload/ordner")
def ordner_importieren(
    request: Request,
    methode: str = Form("schnell"),
    s: Settings = Depends(get_settings),
):
    methoden = _methoden(methode)
    if not _ordner_lock.acquire(blocking=False):
        return templates.TemplateResponse(
            request,
            "upload.html",
            {
                "material_pfad": s.material_pfad,
                "ordner_status": progress.lesen(ORDNER_SCHLUESSEL),
                "fehler": "Ein Ordner-Import läuft bereits.",
            },
            status_code=409,
        )
    progress.starten(ORDNER_SCHLUESSEL)
    try:
        _starte_thread(_ordner_im_hintergrund, methoden, s)
    except Exception:
        _ordner_lock.release()
        raise
    return RedirectResponse(url=f"/laeufe/{ORDNER_SCHLUESSEL}", status_code=303)


@router.get("/laeufe/{schluessel}")
def lauf_status_seite(request: Request, schluessel: str):
    return templates.TemplateResponse(request, "lauf_status.html", {"schluessel": schluessel})


@router.get("/laeufe/{schluessel}/daten")
def lauf_status_daten(schluessel: str):
    status = progress.lesen(schluessel)
    if status is None:
        return {
            "gestartet": False, "schritt": "Kein Lauf gefunden (nach Neustart verloren?)",
            "fertig": True, "fehler": None, "abbruch_angefordert": False, "erledigt": 0,
            "gesamt": 0, "fehlgeschlagen": 0, "begonnen_am": None, "aktualisiert_am": None,
            "verlauf": [],
        }
    return {
        "gestartet": True,
        "schritt": status.schritt,
        "fertig": status.fertig,
        "fehler": status.fehler,
        "abbruch_angefordert": status.abbruch_angefordert,
        "erledigt": status.erledigt,
        "gesamt": status.gesamt,
        "fehlgeschlagen": status.fehlgeschlagen,
        "begonnen_am": status.begonnen_am.isoformat(),
        "aktualisiert_am": status.aktualisiert_am.isoformat(),
        "verlauf": [
            {"text": e.text, "zeitpunkt": e.zeitpunkt.isoformat()}
            for e in status.verlauf[-VERLAUF_ZEILEN:]
        ],
    }


@router.post("/laeufe/{schluessel}/abbrechen")
def lauf_abbrechen(schluessel: str):
    progress.abbruch_anfordern(schluessel)
    return RedirectResponse(url=f"/laeufe/{schluessel}", status_code=303)
