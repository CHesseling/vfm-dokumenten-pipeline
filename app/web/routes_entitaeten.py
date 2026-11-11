from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import get_session
from app.enums import LaufStatus, NerMethode
from app.models import Dokument, Entitaet, Lauf, TextExtraktion
from app.ner.ablauf import ner_ausfuehren, vergleich
from app.ner.treffer import LABELS
from app.providers.llm_client import ProviderFehler
from app.web.vorlagen import templates

router = APIRouter()

LIMIT_JE_LABEL = 200
STANDARD_METHODEN = ["gliner", "muster"]


def markierungen(text: str, entitaeten) -> list[tuple[str, str | None]]:
    """Zerlegt den Text in (Abschnitt, Label|None). Ueberlappende Treffer:
    der laengere gewinnt (bei Gleichstand der fruehere)."""
    angenommen = []
    for e in sorted(entitaeten, key=lambda e: (-(e.ende - e.start), e.start)):
        if e.ende <= e.start or any(e.start < a.ende and a.start < e.ende for a in angenommen):
            continue
        angenommen.append(e)
    segmente: list[tuple[str, str | None]] = []
    pos = 0
    for e in sorted(angenommen, key=lambda e: e.start):
        if e.start > pos:
            segmente.append((text[pos : e.start], None))
        segmente.append((text[e.start : e.ende], e.label))
        pos = e.ende
    if pos < len(text):
        segmente.append((text[pos:], None))
    return segmente


def ner_darstellung(session: Session, extraktion: TextExtraktion | None) -> dict:
    """Vorbereitete Daten fuer den Entitaeten-Abschnitt der Detailseite."""
    if extraktion is None:
        return {"bloecke": [], "vergleich": []}
    alle = session.exec(select(Entitaet).where(Entitaet.textextraktion_id == extraktion.id)).all()
    bloecke = []
    for methode in NerMethode:
        ents = [e for e in alle if e.methode == methode]
        if ents:
            bloecke.append(
                {"methode": methode.value, "anzahl": len(ents), "segmente": markierungen(extraktion.text, ents)}
            )
    return {"bloecke": bloecke, "vergleich": vergleich(session, extraktion.id)}


@router.get("/entitaeten")
def entitaeten_seite(
    request: Request,
    label: str = "",
    q: str = "",
    methode: str = "",
    session: Session = Depends(get_session),
):
    if label not in LABELS:
        label = ""
    if methode not in {m.value for m in NerMethode}:
        methode = ""
    schluessel = func.lower(func.coalesce(Entitaet.normalisiert, Entitaet.text))
    gruppen = []
    for l in [label] if label else LABELS:
        abfrage = (
            select(
                func.min(Entitaet.text),
                func.count(Entitaet.id),
                func.array_agg(func.distinct(TextExtraktion.dokument_id)),
            )
            .join(TextExtraktion, TextExtraktion.id == Entitaet.textextraktion_id)
            .where(Entitaet.label == l, TextExtraktion.ist_aktiv.is_(True))
        )
        if methode:
            abfrage = abfrage.where(Entitaet.methode == NerMethode(methode))
        if q.strip():
            abfrage = abfrage.where(Entitaet.text.ilike(f"%{q.strip()}%"))
        zeilen = session.exec(
            abfrage.group_by(schluessel).order_by(func.count(Entitaet.id).desc(), func.min(Entitaet.text)).limit(LIMIT_JE_LABEL)
        ).all()
        if zeilen:
            gruppen.append((l, zeilen))
    ids = {d for _, zeilen in gruppen for z in zeilen for d in z[2]}
    namen = {d.id: d.dateiname for d in session.exec(select(Dokument).where(Dokument.id.in_(ids))).all()} if ids else {}
    ergebnis = [
        (l, [{"text": t, "anzahl": n, "dokumente": [(d, namen.get(d, str(d))) for d in sorted(dids)]} for t, n, dids in zeilen])
        for l, zeilen in gruppen
    ]
    return templates.TemplateResponse(
        request,
        "entitaeten.html",
        {"gruppen": ergebnis, "labels": LABELS, "label": label, "q": q, "methode": methode,
         "methoden": [m.value for m in NerMethode], "limit": LIMIT_JE_LABEL},
    )


@router.post("/dokumente/{dokument_id}/ner")
def ner_starten(
    dokument_id: int,
    methode: list[str] = Form(default_factory=lambda: list(STANDARD_METHODEN)),
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    if session.get(Dokument, dokument_id) is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    erlaubt = {m.value for m in NerMethode}
    methoden = {NerMethode(m) for m in methode if m in erlaubt} or {NerMethode(m) for m in STANDARD_METHODEN}
    ziel = f"/dokumente/{dokument_id}"
    try:
        bilanz = ner_ausfuehren(session, s, methoden, dokument_id=dokument_id, nur_fehlende=False)
    except ProviderFehler as fehler:
        session.rollback()
        session.add(Lauf(schritt="ner", dokument_id=dokument_id, provider=s.provider, status=LaufStatus.FEHLER,
                         fehler=str(fehler)[:500]))
        session.commit()
        return RedirectResponse(url=f"{ziel}?ner_fehler=1", status_code=303)
    if bilanz.fehler:
        return RedirectResponse(url=f"{ziel}?ner_fehler=1", status_code=303)
    return RedirectResponse(url=ziel, status_code=303)
