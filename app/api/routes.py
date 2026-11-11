"""JSON-API fuer den Recherche-Agenten (Hermes). Die Beschreibungen in /docs dienen als Tool-Doku."""

import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import get_session
from app.embed.rag import antwort_erzeugen
from app.embed.suche import KeineEmbeddingsFehler, semantische_suche, volltext_suche
from app.models import Analyse, Dokument, Entitaet, TextExtraktion
from app.providers.factory import chat_client, embedding_client, reranker
from app.providers.llm_client import ProviderFehler

TEXT_MAX_ZEICHEN = 20000


def token_pruefen(
    authorization: str | None = Header(default=None, include_in_schema=False),
    s: Settings = Depends(get_settings),
) -> None:
    if not s.api_token:
        return
    erwartet = f"Bearer {s.api_token}"
    if authorization is None or not hmac.compare_digest(authorization.encode(), erwartet.encode()):
        raise HTTPException(status_code=401, detail="API-Token fehlt oder falsch")


router = APIRouter(prefix="/api", tags=["agent"], dependencies=[Depends(token_pruefen)])


class SuchErgebnis(BaseModel):
    dokument_id: int = Field(description="ID des Dokuments; mit GET /api/dokumente/{id} abrufbar")
    dateiname: str = Field(description="Ursprünglicher Dateiname des Dokuments")
    typ: str = Field(description="Dokumenttyp: pdf, eml, audio, bild, text oder sonstig")
    ausschnitt: str = Field(description="Passender Textausschnitt (Chunk) aus dem Dokument")
    score: float | None = Field(
        description="Relevanz (höher = besser): Rerank- bzw. Kosinus-Score; bei Volltextsuche null"
    )


class EntitaetInDokument(BaseModel):
    label: str = Field(description="Art der Entität, z. B. person, organisation, ort, iban")
    text: str = Field(description="Erkannter Text, wie er im Dokument steht")
    methode: str = Field(description="Erkennungsmethode: gliner, muster oder llm")


class DokumentAntwort(BaseModel):
    id: int = Field(description="Dokument-ID")
    dateiname: str = Field(description="Ursprünglicher Dateiname")
    typ: str = Field(description="Dokumenttyp: pdf, eml, audio, bild, text oder sonstig")
    metadaten: dict = Field(description="Metadaten des Dokuments (z. B. Absender, Datum, EXIF)")
    text: str = Field(description=f"Aktiver Volltext, auf {TEXT_MAX_ZEICHEN} Zeichen gekürzt")
    text_gekuerzt: bool = Field(description="true, wenn der Text gekürzt wurde")
    entitaeten: list[EntitaetInDokument] = Field(description="Erkannte Entitäten des aktiven Textes")
    analysen: dict[str, dict] = Field(
        description="LLM-Analysen je Art (zusammenfassung, klassifikation, bildbeschreibung)"
    )
    anhaenge: list[int] = Field(description="IDs der Anhänge (Kind-Dokumente), z. B. bei E-Mails")
    parent_id: int | None = Field(description="ID des übergeordneten Dokuments (bei Anhängen), sonst null")


class EntitaetGruppe(BaseModel):
    label: str = Field(description="Art der Entität, z. B. person, organisation, ort")
    text: str = Field(description="Repräsentative Schreibweise der Entität")
    anzahl: int = Field(description="Wie oft die Entität in aktiven Texten vorkommt")
    dokument_ids: list[int] = Field(description="IDs der Dokumente, in denen sie vorkommt")


class FrageAnfrage(BaseModel):
    frage: str = Field(description="Frage in natürlicher Sprache, die anhand der Dokumente beantwortet wird")


class Quelle(BaseModel):
    nummer: int = Field(description="Nummer der Quelle, passend zu [n] im Antworttext")
    dokument_id: int = Field(description="ID des Quelldokuments")
    dateiname: str = Field(description="Dateiname des Quelldokuments")


class FrageAntwort(BaseModel):
    antwort: str = Field(description="Antwort mit Quellenverweisen wie [1]; erfindet nichts außerhalb der Quellen")
    quellen: list[Quelle] = Field(description="Dem Modell übergebene Quellen; [n] im Antworttext verweist auf `nummer`.")


@router.get("/suche", response_model=list[SuchErgebnis], summary="Dokumente durchsuchen")
def suche(
    q: str = Query(description="Suchanfrage (Stichworte bei volltext, ganze Frage/Thema bei semantisch)"),
    modus: Literal["semantisch", "volltext"] = Query(
        "semantisch", description="semantisch = Bedeutungssuche mit Rerank; volltext = Stichwortsuche"
    ),
    top_k: int = Query(8, ge=1, le=50, description="Maximale Anzahl Treffer (1 bis 50)"),
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    try:
        if modus == "volltext":
            treffer = volltext_suche(session, q, limit=top_k)
        else:
            treffer = semantische_suche(
                session, q, embedding_client(s), reranker(s), max(s.rag_top_n, top_k), top_k
            )
    except KeineEmbeddingsFehler as fehler:
        raise HTTPException(status_code=409, detail=str(fehler))
    except ProviderFehler as fehler:
        raise HTTPException(status_code=502, detail=str(fehler))
    typen = {
        d.id: d.typ.value
        for d in session.exec(select(Dokument).where(Dokument.id.in_({t.dokument_id for t in treffer}))).all()
    } if treffer else {}
    return [
        SuchErgebnis(
            dokument_id=t.dokument_id,
            dateiname=t.dateiname,
            typ=typen.get(t.dokument_id, "sonstig"),
            ausschnitt=(t.snippet or t.text).replace("<b>", "").replace("</b>", ""),
            score=t.rerank_score if t.rerank_score is not None else t.vektor_score,
        )
        for t in treffer
    ]


@router.get("/dokumente/{dokument_id}", response_model=DokumentAntwort, summary="Ein Dokument mit Text, Entitäten und Analysen")
def dokument(
    dokument_id: int,
    session: Session = Depends(get_session),
):
    d = session.get(Dokument, dokument_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    aktiv = session.exec(
        select(TextExtraktion).where(TextExtraktion.dokument_id == d.id, TextExtraktion.ist_aktiv.is_(True))
    ).first()
    text = aktiv.text if aktiv else ""
    entitaeten = (
        session.exec(select(Entitaet).where(Entitaet.textextraktion_id == aktiv.id).order_by(Entitaet.start, Entitaet.id)).all()
        if aktiv else []
    )
    analysen = session.exec(select(Analyse).where(Analyse.dokument_id == d.id)).all()
    kinder = session.exec(select(Dokument.id).where(Dokument.parent_id == d.id).order_by(Dokument.id)).all()
    return DokumentAntwort(
        id=d.id, dateiname=d.dateiname, typ=d.typ.value, metadaten=d.metadaten,
        text=text[:TEXT_MAX_ZEICHEN], text_gekuerzt=len(text) > TEXT_MAX_ZEICHEN,
        entitaeten=[EntitaetInDokument(label=e.label, text=e.text, methode=e.methode.value) for e in entitaeten],
        analysen={a.art.value: a.ergebnis for a in analysen},
        anhaenge=list(kinder), parent_id=d.parent_id,
    )


@router.get("/entitaeten", response_model=list[EntitaetGruppe], summary="Entitäten über alle Dokumente")
def entitaeten(
    label: str = Query("", description="Nur diese Art, z. B. person, organisation, ort, iban (leer = alle)"),
    q: str = Query("", description="Teilstring im Entitätstext (Groß-/Kleinschreibung egal)"),
    limit: int = Query(50, ge=1, le=500, description="Maximale Anzahl Gruppen"),
    session: Session = Depends(get_session),
):
    schluessel = func.lower(func.coalesce(Entitaet.normalisiert, Entitaet.text))
    abfrage = (
        select(
            Entitaet.label,
            func.min(Entitaet.text),
            func.count(Entitaet.id),
            func.array_agg(func.distinct(TextExtraktion.dokument_id)),
        )
        .join(TextExtraktion, TextExtraktion.id == Entitaet.textextraktion_id)
        .where(TextExtraktion.ist_aktiv.is_(True))
    )
    if label:
        abfrage = abfrage.where(Entitaet.label == label)
    if q.strip():
        abfrage = abfrage.where(Entitaet.text.ilike(f"%{q.strip()}%"))
    zeilen = session.exec(
        abfrage.group_by(Entitaet.label, schluessel)
        .order_by(func.count(Entitaet.id).desc(), func.min(Entitaet.text))
        .limit(limit)
    ).all()
    return [
        EntitaetGruppe(label=l, text=t, anzahl=n, dokument_ids=sorted(ids)) for l, t, n, ids in zeilen
    ]


@router.post("/frage", response_model=FrageAntwort, summary="Frage anhand der Dokumente beantworten (RAG)")
def frage(
    daten: FrageAnfrage,
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    try:
        treffer = semantische_suche(session, daten.frage, embedding_client(s), reranker(s), s.rag_top_n, s.rag_top_k)
        antwort = antwort_erzeugen(chat_client(s), daten.frage, treffer)
    except KeineEmbeddingsFehler as fehler:
        raise HTTPException(status_code=409, detail=str(fehler))
    except ProviderFehler as fehler:
        raise HTTPException(status_code=502, detail=str(fehler))
    return FrageAntwort(
        antwort=antwort.text,
        quellen=[
            Quelle(nummer=n, dokument_id=t.dokument_id, dateiname=t.dateiname)
            for n, t in enumerate(antwort.quellen, 1)
        ],
    )
