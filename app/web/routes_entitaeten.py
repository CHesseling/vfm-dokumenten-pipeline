from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import get_session
from app.enums import LaufStatus, NerMethode
from app.models import Dokument, Entitaet, Lauf, TextExtraktion
from app.ner.ablauf import entitaeten_loeschen, ner_ausfuehren, vergleich
from app.ner.labels import labels_parsen, schwelle_pruefen
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
                {"methode": methode.value, "anzahl": len(ents), "segmente": markierungen(extraktion.text, ents),
                 "parameter": _parameter_text(session, extraktion, methode)}
            )
    return {"bloecke": bloecke, "vergleich": vergleich(session, extraktion.id)}


def _parameter_text(session: Session, extraktion: TextExtraktion, methode: NerMethode) -> str | None:
    """Parameter des juengsten erfolgreichen Laufs dieser Methode fuer diese Extraktion."""
    laeufe = session.exec(
        select(Lauf)
        .where(Lauf.dokument_id == extraktion.dokument_id, Lauf.schritt == f"ner:{methode.value}",
               Lauf.status == LaufStatus.ERFOLG)
        .order_by(Lauf.id.desc())
    ).all()
    roh = next(((l.roh_output or {}) for l in laeufe if (l.roh_output or {}).get("extraktion_id") == extraktion.id), {})
    teile = []
    if "schwelle" in roh:
        teile.append(f"Schwelle {roh['schwelle']}")
    if roh.get("labels"):
        teile.append(f"Labels: {roh['labels']}")
    return " · ".join(teile) or None


def eigene_labels(session: Session) -> list[str]:
    """Labels aktiver Extraktionen, die nicht zu den Standard-Labels gehoeren (sortiert)."""
    zeilen = session.exec(
        select(Entitaet.label)
        .join(TextExtraktion, TextExtraktion.id == Entitaet.textextraktion_id)
        .where(TextExtraktion.ist_aktiv.is_(True), Entitaet.label.not_in(LABELS))
        .distinct()
    ).all()
    return sorted(zeilen)


@router.get("/entitaeten")
def entitaeten_seite(
    request: Request,
    label: str = "",
    q: str = "",
    methode: str = "",
    session: Session = Depends(get_session),
):
    alle_labels = [*LABELS, *eigene_labels(session)]
    if label not in alle_labels:
        label = ""
    if methode not in {m.value for m in NerMethode}:
        methode = ""
    schluessel = func.lower(func.coalesce(Entitaet.normalisiert, Entitaet.text))
    gruppen = []
    for l in [label] if label else alle_labels:
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
        {"gruppen": ergebnis, "labels": alle_labels, "label": label, "q": q, "methode": methode,
         "methoden": [m.value for m in NerMethode], "limit": LIMIT_JE_LABEL},
    )


@router.post("/dokumente/{dokument_id}/ner")
def ner_starten(
    dokument_id: int,
    methode: list[str] = Form(default_factory=lambda: list(STANDARD_METHODEN)),
    labels: str = Form(""),
    schwelle: str = Form(""),
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    if session.get(Dokument, dokument_id) is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    erlaubt = {m.value for m in NerMethode}
    methoden = {NerMethode(m) for m in methode if m in erlaubt} or {NerMethode(m) for m in STANDARD_METHODEN}
    ziel = f"/dokumente/{dokument_id}"
    try:
        label_liste = labels_parsen(labels)
        schwelle_wert = schwelle_pruefen(float(schwelle)) if schwelle.strip() else None
    except ValueError:
        return RedirectResponse(url=f"{ziel}?parameter_fehler=1", status_code=303)
    try:
        bilanz = ner_ausfuehren(session, s, methoden, dokument_id=dokument_id, labels=label_liste,
                                schwelle=schwelle_wert, nur_fehlende=False)
    except ProviderFehler as fehler:
        session.rollback()
        session.add(Lauf(schritt="ner", dokument_id=dokument_id, provider=s.provider, status=LaufStatus.FEHLER,
                         fehler=str(fehler)[:500]))
        session.commit()
        return RedirectResponse(url=f"{ziel}?ner_fehler=1", status_code=303)
    if bilanz.fehler:
        return RedirectResponse(url=f"{ziel}?ner_fehler=1", status_code=303)
    return RedirectResponse(url=ziel, status_code=303)


@router.post("/dokumente/{dokument_id}/entitaeten/loeschen")
def entitaeten_loeschen_route(
    dokument_id: int,
    methode: str = Form(...),
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    if session.get(Dokument, dokument_id) is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    if methode == "alle":
        methoden = set(NerMethode)
    elif methode in {m.value for m in NerMethode}:
        methoden = {NerMethode(methode)}
    else:
        raise HTTPException(status_code=400, detail="Unbekannte Methode")
    extraktion = session.exec(
        select(TextExtraktion).where(TextExtraktion.dokument_id == dokument_id, TextExtraktion.ist_aktiv.is_(True))
    ).first()
    if extraktion is not None:
        entitaeten_loeschen(session, extraktion.id, methoden, s.provider)
        session.commit()
    return RedirectResponse(url=f"/dokumente/{dokument_id}", status_code=303)
