import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.analyse.ablauf import analyse_ausfuehren
from app.config import Settings, get_settings
from app.db import get_session
from app.enums import AnalyseArt, DokumentTyp
from app.ingest.speichern import aktiv_setzen
from app.models import (
    Analyse, Chunk, Dokument, Embedding, Entitaet, Lauf, TextExtraktion,
)
from app.web.routes_entitaeten import ner_darstellung
from app.web.vorlagen import templates

logger = logging.getLogger(__name__)

router = APIRouter()

SEITENGROESSE = 50


@router.get("/")
def startseite():
    return RedirectResponse(url="/dokumente", status_code=307)


def _menge(session: Session, spalte, bedingung) -> set[int]:
    return set(session.exec(select(spalte).where(bedingung).distinct()).all())


@router.get("/dokumente")
def dokumente_liste(
    request: Request,
    typ: str = "",
    q: str = "",
    kategorie: str = "",
    seite: int = 1,
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    seite = max(seite, 1)
    abfrage = select(Dokument)
    zaehler = select(func.count()).select_from(Dokument)
    if typ in {t.value for t in DokumentTyp}:
        abfrage = abfrage.where(Dokument.typ == DokumentTyp(typ))
        zaehler = zaehler.where(Dokument.typ == DokumentTyp(typ))
    else:
        typ = ""
    if q.strip():
        muster = f"%{q.strip()}%"
        abfrage = abfrage.where(Dokument.dateiname.ilike(muster))
        zaehler = zaehler.where(Dokument.dateiname.ilike(muster))
    if kategorie.strip():
        passende = select(Analyse.dokument_id).where(
            Analyse.art == AnalyseArt.KLASSIFIKATION, Analyse.ergebnis["kategorie"].astext == kategorie
        )
        abfrage = abfrage.where(Dokument.id.in_(passende))
        zaehler = zaehler.where(Dokument.id.in_(passende))
    gesamt = session.exec(zaehler).one()
    dokumente = session.exec(
        abfrage.order_by(Dokument.erstellt_am.desc(), Dokument.id.desc())
        .offset((seite - 1) * SEITENGROESSE)
        .limit(SEITENGROESSE)
    ).all()
    ids = [d.id for d in dokumente]

    mit_text = _menge(session, TextExtraktion.dokument_id, TextExtraktion.dokument_id.in_(ids))
    entitaeten = dict(
        session.exec(
            select(TextExtraktion.dokument_id, func.count(Entitaet.id))
            .join(Entitaet, Entitaet.textextraktion_id == TextExtraktion.id)
            .where(TextExtraktion.dokument_id.in_(ids))
            .group_by(TextExtraktion.dokument_id)
        ).all()
    )
    mit_embedding = set(
        session.exec(
            select(TextExtraktion.dokument_id)
            .join(Chunk, Chunk.textextraktion_id == TextExtraktion.id)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
            .where(TextExtraktion.dokument_id.in_(ids), Embedding.modell == s.embed_model)
            .distinct()
        ).all()
    )
    mit_analyse = _menge(session, Analyse.dokument_id, Analyse.dokument_id.in_(ids))
    kategorien = dict(
        session.exec(
            select(Analyse.dokument_id, Analyse.ergebnis["kategorie"].astext).where(
                Analyse.art == AnalyseArt.KLASSIFIKATION, Analyse.dokument_id.in_(ids)
            )
        ).all()
    )
    alle_kategorien = sorted(
        k for k in session.exec(
            select(Analyse.ergebnis["kategorie"].astext)
            .where(Analyse.art == AnalyseArt.KLASSIFIKATION).distinct()
        ).all() if k
    )
    eltern = {
        d.id: d
        for d in session.exec(
            select(Dokument).where(Dokument.id.in_([d.parent_id for d in dokumente if d.parent_id]))
        ).all()
    }
    zeilen = [
        {
            "dokument": d,
            "datum": d.metadaten.get("datum") or d.erstellt_am.strftime("%d.%m.%Y %H:%M"),
            "eltern": eltern.get(d.parent_id),
            "text": d.id in mit_text,
            "entitaeten": entitaeten.get(d.id, 0),
            "embedding": d.id in mit_embedding,
            "analyse": d.id in mit_analyse,
            "kategorie": kategorien.get(d.id),
        }
        for d in dokumente
    ]
    return templates.TemplateResponse(
        request,
        "dokumente.html",
        {
            "zeilen": zeilen,
            "typen": [t.value for t in DokumentTyp],
            "typ": typ,
            "q": q,
            "kategorie": kategorie,
            "kategorien": alle_kategorien,
            "seite": seite,
            "gesamt": gesamt,
            "hat_weitere": seite * SEITENGROESSE < gesamt,
        },
    )


@router.get("/dokumente/{dokument_id}")
def dokument_detail(
    request: Request,
    dokument_id: int,
    ner_fehler: str = "",
    analyse_fehler: str = "",
    session: Session = Depends(get_session),
):
    dokument = session.get(Dokument, dokument_id)
    if dokument is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    extraktionen = session.exec(
        select(TextExtraktion)
        .where(TextExtraktion.dokument_id == dokument_id)
        .order_by(TextExtraktion.id)
    ).all()
    kinder = session.exec(
        select(Dokument).where(Dokument.parent_id == dokument_id).order_by(Dokument.id)
    ).all()
    eltern = session.get(Dokument, dokument.parent_id) if dokument.parent_id else None
    laeufe = session.exec(
        select(Lauf).where(Lauf.dokument_id == dokument_id).order_by(Lauf.id)
    ).all()
    analysen = {a.art.value: a.ergebnis for a in session.exec(select(Analyse).where(Analyse.dokument_id == dokument_id)).all()}
    return templates.TemplateResponse(
        request,
        "dokument_detail.html",
        {
            "dokument": dokument,
            "extraktionen": extraktionen,
            "kinder": kinder,
            "eltern": eltern,
            "laeufe": laeufe,
            "ner": ner_darstellung(session, next((e for e in extraktionen if e.ist_aktiv), None)),
            # nur ein Flag, nie Text aus dem Querystring ausgeben
            "ner_fehler": bool(ner_fehler),
            "analyse_fehler": bool(analyse_fehler),
            "analysen": analysen,
        },
    )


@router.get("/dokumente/{dokument_id}/datei")
def dokument_datei(
    dokument_id: int,
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    dokument = session.get(Dokument, dokument_id)
    if dokument is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    pfad = Path(dokument.dateipfad(s.daten_pfad))
    if not pfad.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht auf dem Datenträger")
    return FileResponse(
        pfad,
        media_type=dokument.mime,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(dokument.dateiname)}"
        },
    )


@router.post("/dokumente/{dokument_id}/aktiv/{extraktion_id}")
def extraktion_aktiv(
    dokument_id: int,
    extraktion_id: int,
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    extraktion = session.get(TextExtraktion, extraktion_id)
    if extraktion is None or extraktion.dokument_id != dokument_id:
        raise HTTPException(status_code=404, detail="Extraktion nicht gefunden")
    aktiv_setzen(session, extraktion_id, s)
    session.commit()
    return RedirectResponse(url=f"/dokumente/{dokument_id}", status_code=303)


@router.post("/dokumente/{dokument_id}/analyse")
def analyse_starten(
    dokument_id: int,
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    if session.get(Dokument, dokument_id) is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    ziel = f"/dokumente/{dokument_id}"
    try:
        bilanz = analyse_ausfuehren(session, s, set(AnalyseArt), dokument_id=dokument_id, nur_fehlende=False)
    except Exception:  # noqa: BLE001 - Details stehen im Log, die Seite zeigt nur den festen Hinweis
        logger.exception("Analyse fuer Dokument %s fehlgeschlagen", dokument_id)
        session.rollback()
        return RedirectResponse(url=f"{ziel}?analyse_fehler=1", status_code=303)
    if bilanz.fehler:
        return RedirectResponse(url=f"{ziel}?analyse_fehler=1", status_code=303)
    return RedirectResponse(url=ziel, status_code=303)
