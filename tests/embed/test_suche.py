from sqlalchemy import select
import pytest

from app.embed.suche import KeineEmbeddingsFehler, semantische_suche
from app.enums import DokumentTyp
from app.models import Dokument, Embedding
from app.providers.rerank import KeinReranker
from tests.embed.test_index import chunks_anlegen


class FakeEmbed:
    def __init__(self, model, vektor):
        self.model = model
        self._v = vektor

    def embed(self, text):
        return self._v


class Umkehr:
    def rerank(self, frage, texte):
        return [(i, float(i)) for i in reversed(range(len(texte)))]


def vorbereiten(session, modell="b", vektoren=None):
    chunks = chunks_anlegen(session, ["nah", "mittel", "fern"])
    vektoren = vektoren or [[1.0, 0.0], [0.7, 0.7], [0.0, 1.0]]
    for c, v in zip(chunks, vektoren):
        session.add(Embedding(chunk_id=c.id, modell=modell, vektor=v))
    session.commit()
    return chunks


def test_semantisch_nur_aktuelles_modell(session):
    vorbereiten(session, "b")
    # Modell "a" mit ANDERER Dimension und Chunks, die sonst ganz vorn laegen
    andere = chunks_anlegen(session, ["a-chunk"], sha="s2")
    session.add(Embedding(chunk_id=andere[0].id, modell="a", vektor=[1.0, 0.0, 0.0]))
    session.commit()
    t = semantische_suche(session, "x", FakeEmbed("b", [1.0, 0.0]), KeinReranker(), 10, 10)
    assert [x.text for x in t] == ["nah", "mittel", "fern"]
    t_a = semantische_suche(session, "x", FakeEmbed("a", [1.0, 0.0, 0.0]), KeinReranker(), 10, 10)
    assert [x.text for x in t_a] == ["a-chunk"]


def test_keine_embeddings_meldung(session):
    chunks_anlegen(session, ["x"])
    with pytest.raises(KeineEmbeddingsFehler) as e:
        semantische_suche(session, "x", FakeEmbed("m", [1.0]), KeinReranker(), 5, 5)
    assert "Für Modell m gibt es noch keine Embeddings – erst `vfm embed` ausführen" in str(e.value)


def test_rerank_aendert_reihenfolge(session):
    vorbereiten(session)
    t = semantische_suche(session, "x", FakeEmbed("b", [1.0, 0.0]), Umkehr(), 3, 2)
    assert [x.text for x in t] == ["fern", "mittel"]
    assert (t[0].vektor_rang, t[0].rerank_rang) == (3, 1)
    assert t[0].rerank_score == 2.0
    assert t[1].vektor_rang == 2 and t[1].rerank_rang == 2
    assert 0.99 > t[1].vektor_score > 0.5


def test_ohne_rerank_vektor_reihenfolge(session):
    vorbereiten(session)
    t = semantische_suche(session, "x", FakeEmbed("b", [1.0, 0.0]), KeinReranker(), 3, 2)
    assert [x.text for x in t] == ["nah", "mittel"]
    assert [x.vektor_rang for x in t] == [1, 2]
    assert all(x.rerank_rang is None and x.rerank_score is None for x in t)
    assert t[0].vektor_score == pytest.approx(1.0)


def test_typ_filter(session):
    vorbereiten(session)
    pdf = chunks_anlegen(session, ["pdf-chunk"], sha="s3")
    dok = session.scalars(select(Dokument).where(Dokument.sha256 == "s3")).one()
    dok.typ = DokumentTyp.PDF
    session.add(Embedding(chunk_id=pdf[0].id, modell="b", vektor=[1.0, 0.1]))
    session.commit()
    t = semantische_suche(session, "x", FakeEmbed("b", [1.0, 0.0]), KeinReranker(), 10, 10, DokumentTyp.PDF)
    assert [x.text for x in t] == ["pdf-chunk"]
