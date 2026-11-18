import json

import httpx
import respx
from sqlalchemy import select

from app.embed.index import embed_ausfuehren, embeddings_loeschen, vorhandene_modelle
from app.enums import DokumentTyp, ExtraktionsMethode
from app.models import Chunk, Dokument, Embedding, Lauf, TextExtraktion
from app.providers.embeddings import EmbeddingClient

URL = "http://embed.example/v1/embeddings"


def chunks_anlegen(session, texte, aktiv=True, sha="s1"):
    d = Dokument(sha256=sha, dateiname=f"{sha}.txt", typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    ex = TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text=" ".join(texte), ist_aktiv=aktiv)
    session.add(ex)
    session.flush()
    chunks = [Chunk(textextraktion_id=ex.id, position=i, start=0, ende=len(t), text=t) for i, t in enumerate(texte)]
    session.add_all(chunks)
    session.commit()
    return chunks


def antwort(request):
    eingabe = json.loads(request.content)["input"]
    daten = [{"index": i, "embedding": [1.0, float(len(t)), 0.5]} for i, t in enumerate(eingabe)]
    return httpx.Response(200, json={"data": daten})


@respx.mock
def test_nur_fehlende(session):
    c1, c2 = chunks_anlegen(session, ["eins", "zwei"])
    session.add(Embedding(chunk_id=c1.id, modell="m", vektor=[1.0, 2.0, 3.0]))
    session.commit()
    route = respx.post(URL).mock(side_effect=antwort)
    client = EmbeddingClient(base_url="http://embed.example/v1", model="m")

    bilanz = embed_ausfuehren(session, client)

    assert route.call_count == 1
    assert json.loads(route.calls[0].request.content)["input"] == ["zwei"]
    assert (bilanz.neu, bilanz.vorhanden, bilanz.dimension) == (1, 1, 3)
    lauf = session.scalars(select(Lauf).where(Lauf.schritt == "embed")).all()
    assert len(lauf) == 1 and lauf[0].modell == "m" and lauf[0].roh_output == {"neu": 1, "dimension": 3}


@respx.mock
def test_anderes_modell_neu(session):
    c1, c2 = chunks_anlegen(session, ["eins", "zwei"])
    session.add(Embedding(chunk_id=c1.id, modell="a", vektor=[1.0, 2.0]))
    session.commit()
    respx.post(URL).mock(side_effect=antwort)
    client = EmbeddingClient(base_url="http://embed.example/v1", model="b")

    bilanz = embed_ausfuehren(session, client)

    assert bilanz.neu == 2 and bilanz.vorhanden == 0
    assert sorted(vorhandene_modelle(session)) == [("a", 1), ("b", 2)]


@respx.mock
def test_keine_chunks(session):
    route = respx.post(URL).mock(side_effect=antwort)
    client = EmbeddingClient(base_url="http://embed.example/v1", model="m")

    bilanz = embed_ausfuehren(session, client)

    assert bilanz.neu == 0 and bilanz.dimension is None
    assert route.call_count == 0


@respx.mock
def test_inaktive_extraktion_ignoriert(session):
    chunks_anlegen(session, ["eins"], aktiv=False)
    route = respx.post(URL).mock(side_effect=antwort)
    client = EmbeddingClient(base_url="http://embed.example/v1", model="m")
    assert embed_ausfuehren(session, client).neu == 0
    assert route.call_count == 0


@respx.mock
def test_alle_neu_ersetzt(session):
    c1, = chunks_anlegen(session, ["eins"])
    session.add(Embedding(chunk_id=c1.id, modell="m", vektor=[9.0]))
    session.commit()
    respx.post(URL).mock(side_effect=antwort)
    client = EmbeddingClient(base_url="http://embed.example/v1", model="m")

    bilanz = embed_ausfuehren(session, client, nur_fehlende=False)

    assert bilanz.neu == 1
    assert [float(x) for x in session.scalars(select(Embedding)).one().vektor] == [1.0, 4.0, 0.5]


@respx.mock
def test_abbrechen_und_fortschritt(session):
    chunks_anlegen(session, ["a", "b", "c"])
    respx.post(URL).mock(side_effect=antwort)
    client = EmbeddingClient(base_url="http://embed.example/v1", model="m", batch=1)
    stand = []

    bilanz = embed_ausfuehren(
        session, client, bei_fortschritt=lambda n, g: stand.append((n, g)), soll_abbrechen=lambda: len(stand) >= 2
    )

    assert bilanz.neu == 2 and stand == [(1, 3), (2, 3)]


def _zwei_dokumente_mit_embeddings(session):
    c1 = chunks_anlegen(session, ["eins", "zwei"], sha="s1")
    c2 = chunks_anlegen(session, ["drei"], sha="s2")
    for c in c1 + c2:
        for modell in ("a", "b"):
            session.add(Embedding(chunk_id=c.id, modell=modell, vektor=[1.0, 2.0, 3.0]))
    session.commit()
    dok1 = session.get(TextExtraktion, c1[0].textextraktion_id).dokument_id
    return dok1, c1, c2


def _bestand(session):
    return sorted((e.chunk_id, e.modell) for e in session.scalars(select(Embedding)).all())


def test_embeddings_loeschen_aktuelles_modell(session):
    dok1, c1, c2 = _zwei_dokumente_mit_embeddings(session)
    n = embeddings_loeschen(session, dok1, "a", "ollama")
    session.commit()
    assert n == 2
    erwartet = sorted([(c.id, "b") for c in c1] + [(c2[0].id, "a"), (c2[0].id, "b")])
    assert _bestand(session) == erwartet
    lauf = session.scalars(select(Lauf).where(Lauf.schritt == "loeschen:embed")).one()
    assert lauf.roh_output == {"geloescht": 2} and lauf.modell == "a" and lauf.dokument_id == dok1


def test_embeddings_loeschen_alle_modelle(session):
    dok1, c1, c2 = _zwei_dokumente_mit_embeddings(session)
    assert embeddings_loeschen(session, dok1, None, "ollama") == 4
    session.commit()
    assert _bestand(session) == [(c2[0].id, "a"), (c2[0].id, "b")]
