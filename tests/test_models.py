import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.enums import DokumentTyp, ExtraktionsMethode, NerMethode
from app.models.auswertung import Chunk, Embedding, Entitaet
from app.models.dokument import Dokument, TextExtraktion


def _dokument(sha="a" * 64):
    return Dokument(sha256=sha, dateiname="x.pdf", typ=DokumentTyp.PDF,
                    mime="application/pdf", groesse=10)


def _extraktion(session, sha="a" * 64):
    dok = _dokument(sha)
    session.add(dok)
    session.commit()
    ex = TextExtraktion(dokument_id=dok.id, methode=ExtraktionsMethode.SCHNELL,
                        text="Die Rechnung kam", dauer_ms=1)
    session.add(ex)
    session.commit()
    return dok, ex


def _chunk(session, ex):
    chunk = Chunk(textextraktion_id=ex.id, position=0, start=0, ende=16,
                  text="Die Rechnung kam")
    session.add(chunk)
    session.commit()
    return chunk


def test_embedding_verschiedene_dimensionen(session):
    _, ex = _extraktion(session)
    chunk = _chunk(session, ex)
    session.add(Embedding(chunk_id=chunk.id, modell="a", vektor=[1.0, 2.0, 3.0]))
    session.add(Embedding(chunk_id=chunk.id, modell="b", vektor=[1, 2, 3, 4, 5]))
    session.commit()
    session.expire_all()
    emb = {e.modell: list(e.vektor) for e in session.exec(select(Embedding)).all()}
    assert emb["a"] == [1.0, 2.0, 3.0]
    assert len(emb["b"]) == 5


def test_chunk_tsvector_wird_berechnet(session):
    _, ex = _extraktion(session)
    chunk = _chunk(session, ex)
    treffer = session.execute(
        text("SELECT tsv @@ to_tsquery('german','Rechnungen') FROM chunk WHERE id=:i"),
        {"i": chunk.id},
    ).scalar()
    assert treffer is True


def test_sha256_unique(session):
    session.add(_dokument())
    session.commit()
    session.add(_dokument())
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_extraktion_loeschen_kaskadiert(session):
    _, ex = _extraktion(session)
    chunk = _chunk(session, ex)
    session.add(Embedding(chunk_id=chunk.id, modell="a", vektor=[1.0, 2.0]))
    session.add(Entitaet(textextraktion_id=ex.id, methode=NerMethode.MUSTER,
                         label="PER", text="Max", start=0, ende=3))
    session.commit()
    session.execute(text("DELETE FROM textextraktion WHERE id=:i"), {"i": ex.id})
    session.commit()
    for tabelle in ("chunk", "embedding", "entitaet"):
        assert session.execute(text(f"SELECT count(*) FROM {tabelle}")).scalar() == 0


def test_dateipfad():
    from pathlib import Path
    assert _dokument("ab" + "c" * 62).dateipfad("/d") == Path("/d/ab/" + "ab" + "c" * 62)
