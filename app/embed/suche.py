"""Semantische Suche: Vektor-Treffer (exakt, Kosinus) und Rerank."""

from sqlalchemy import func, select
from sqlmodel import Session

from app.embed.treffer import SuchTreffer
from app.embed.volltext import volltext_suche  # noqa: F401 - bequemer Import
from app.enums import DokumentTyp
from app.models import Chunk, Dokument, Embedding, TextExtraktion
from app.providers.embeddings import EmbeddingClient
from app.providers.rerank import KeinReranker, Reranker

__all__ = ["KeineEmbeddingsFehler", "SuchTreffer", "semantische_suche", "volltext_suche"]


class KeineEmbeddingsFehler(Exception):
    def __init__(self, modell: str):
        self.modell = modell
        super().__init__(f"Für Modell {modell} gibt es noch keine Embeddings – erst `vfm embed` ausführen")


def semantische_suche(
    session: Session,
    anfrage: str,
    embed: EmbeddingClient,
    reranker: Reranker,
    top_n: int,
    top_k: int,
    dokument_typ: DokumentTyp | None = None,
) -> list[SuchTreffer]:
    if session.scalar(select(func.count()).select_from(Embedding).where(Embedding.modell == embed.model)) == 0:
        raise KeineEmbeddingsFehler(embed.model)
    vektor = embed.embed(anfrage)
    distanz = Embedding.vektor.cosine_distance(vektor)
    abfrage = (
        select(Chunk.id, Dokument.id, Dokument.dateiname, Chunk.text, distanz)
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .join(TextExtraktion, TextExtraktion.id == Chunk.textextraktion_id)
        .join(Dokument, Dokument.id == TextExtraktion.dokument_id)
        .where(
            Embedding.modell == embed.model,
            # Dimensionen koennen je Modell verschieden sein: nie ungleiche Vektoren vergleichen
            func.vector_dims(Embedding.vektor) == len(vektor),
            TextExtraktion.ist_aktiv.is_(True),
        )
        .order_by(distanz, Chunk.id)
        .limit(top_n)
    )
    if dokument_typ is not None:
        abfrage = abfrage.where(Dokument.typ == dokument_typ)
    treffer = [
        SuchTreffer(
            chunk_id=cid, dokument_id=did, dateiname=name, text=text, vektor_rang=rang,
            vektor_score=1.0 - float(dist), rerank_rang=None, rerank_score=None,
        )
        for rang, (cid, did, name, text, dist) in enumerate(session.execute(abfrage).all(), 1)
    ]
    if not treffer or isinstance(reranker, KeinReranker):
        return treffer[:top_k]
    sortiert = reranker.rerank(anfrage, [t.text for t in treffer])
    ergebnis = []
    for rang, (index, score) in enumerate(sortiert, 1):
        t = treffer[index]
        t.rerank_rang, t.rerank_score = rang, float(score)
        ergebnis.append(t)
    return ergebnis[:top_k]
