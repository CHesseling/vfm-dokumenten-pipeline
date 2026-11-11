"""Zaehlerstaende: wie weit die Dokumente je Typ verarbeitet sind (`vfm status` und Status-Seite)."""

from sqlalchemy import distinct, func, select
from sqlmodel import Session

from app.config import Settings
from app.models import Analyse, Chunk, Dokument, Embedding, Entitaet, TextExtraktion

STUFEN = ("gesamt", "mit_text", "mit_entitaeten", "mit_embeddings", "mit_analyse")


def zaehlerstaende(session: Session, s: Settings) -> dict[str, dict]:
    """Je Stufe: {DokumentTyp: Anzahl Dokumente}."""

    def zaehle(*stufen) -> dict:
        abfrage = select(Dokument.typ, func.count(distinct(Dokument.id))).group_by(Dokument.typ)
        for joins in stufen:
            abfrage = joins(abfrage)
        return {typ: n for typ, n in session.execute(abfrage).all()}

    aktiv = lambda q: q.join(TextExtraktion, TextExtraktion.dokument_id == Dokument.id).where(
        TextExtraktion.ist_aktiv.is_(True)
    )
    return {
        "gesamt": zaehle(),
        "mit_text": zaehle(aktiv),
        "mit_entitaeten": zaehle(
            aktiv, lambda q: q.join(Entitaet, Entitaet.textextraktion_id == TextExtraktion.id)
        ),
        "mit_embeddings": zaehle(
            aktiv,
            lambda q: q.join(Chunk, Chunk.textextraktion_id == TextExtraktion.id)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
            .where(Embedding.modell == s.embed_model),
        ),
        "mit_analyse": zaehle(lambda q: q.join(Analyse, Analyse.dokument_id == Dokument.id)),
    }
