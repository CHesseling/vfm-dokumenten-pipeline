"""Embeddings je Modell erzeugen (Chunks aktiver Extraktionen)."""

import time
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlmodel import Session

from app.enums import LaufStatus
from app.models import Chunk, Embedding, Lauf, TextExtraktion
from app.providers.embeddings import EmbeddingClient


@dataclass
class EmbedBilanz:
    neu: int
    vorhanden: int
    dimension: int | None


def _aktive_chunks(modell: str):
    return (
        select(Chunk.id, Chunk.text)
        .join(TextExtraktion, TextExtraktion.id == Chunk.textextraktion_id)
        .where(TextExtraktion.ist_aktiv.is_(True))
    )


def embed_ausfuehren(
    session: Session,
    client: EmbeddingClient,
    nur_fehlende: bool = True,
    bei_fortschritt=None,
    soll_abbrechen=None,
    provider: str = "",
) -> EmbedBilanz:
    """Embeddet alle Chunks aktiver Extraktionen, die fuer client.model noch fehlen.

    nur_fehlende=False ersetzt vorhandene Embeddings dieses Modells.
    Ein Lauf pro Aufruf. Commit erfolgt je Batch, Abbruch behaelt Fertiges."""
    start = time.monotonic()
    alle = session.execute(_aktive_chunks(client.model).order_by(Chunk.id)).all()
    vorhanden_ids = set(
        session.scalars(select(Embedding.chunk_id).where(Embedding.modell == client.model)).all()
    )
    vorhanden = sum(1 for cid, _ in alle if cid in vorhanden_ids)
    offen = [(cid, t) for cid, t in alle if not nur_fehlende or cid not in vorhanden_ids]
    if not nur_fehlende:
        vorhanden = 0
    neu = 0
    dimension = None
    for von in range(0, len(offen), client.batch):
        if soll_abbrechen is not None and soll_abbrechen():
            break
        stapel = offen[von : von + client.batch]
        vektoren = client.embed_viele([t for _, t in stapel])
        ids = [cid for cid, _ in stapel]
        session.execute(delete(Embedding).where(Embedding.modell == client.model, Embedding.chunk_id.in_(ids)))
        for cid, vektor in zip(ids, vektoren):
            session.add(Embedding(chunk_id=cid, modell=client.model, vektor=vektor))
        session.commit()
        neu += len(stapel)
        dimension = len(vektoren[0]) if vektoren else dimension
        if bei_fortschritt is not None:
            bei_fortschritt(neu, len(offen))
    if neu:
        session.add(Lauf(
            schritt="embed", provider=provider or client.rolle, modell=client.model,
            dauer_ms=int((time.monotonic() - start) * 1000), status=LaufStatus.ERFOLG,
            roh_output={"neu": neu, "dimension": dimension},
        ))
        session.commit()
    if dimension is None and vorhanden:
        dimension = session.scalar(
            select(func.vector_dims(Embedding.vektor)).where(Embedding.modell == client.model).limit(1)
        )
    return EmbedBilanz(neu=neu, vorhanden=vorhanden, dimension=dimension)


def vorhandene_modelle(session: Session) -> list[tuple[str, int]]:
    zeilen = session.execute(
        select(Embedding.modell, func.count()).group_by(Embedding.modell).order_by(Embedding.modell)
    ).all()
    return [(m, n) for m, n in zeilen]


def embeddings_loeschen(session: Session, dokument_id: int, modell: str | None, provider: str) -> int:
    """Loescht Embeddings aller Chunks des Dokuments (modell=None: alle Modelle).
    Protokolliert einen Lauf `loeschen:embed`. Nur flush, Commit macht der Aufrufer."""
    chunk_ids = (
        select(Chunk.id)
        .join(TextExtraktion, TextExtraktion.id == Chunk.textextraktion_id)
        .where(TextExtraktion.dokument_id == dokument_id)
    )
    bedingung = Embedding.chunk_id.in_(chunk_ids)
    if modell is not None:
        bedingung = bedingung & (Embedding.modell == modell)
    anzahl = session.execute(delete(Embedding).where(bedingung)).rowcount or 0
    session.add(Lauf(schritt="loeschen:embed", dokument_id=dokument_id, provider=provider, modell=modell,
                     status=LaufStatus.ERFOLG, roh_output={"geloescht": anzahl}))
    session.flush()
    return anzahl
