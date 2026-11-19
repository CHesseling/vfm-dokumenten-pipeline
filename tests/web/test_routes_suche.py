import httpx
import respx

from app.models import Embedding
from tests.embed.test_index import chunks_anlegen


def test_suche_seite_volltext(client, session):
    chunks_anlegen(session, ["Die Rechnung liegt vor."])
    r = client.get("/suche", params={"q": "Rechnungen", "modus": "volltext"})
    assert r.status_code == 200
    assert "s1.txt" in r.text and "<b>Rechnung</b>" in r.text
    assert 'href="/dokumente/' in r.text


def test_suche_leer(client):
    assert client.get("/suche").status_code == 200


def test_suche_ohne_embeddings_zeigt_hinweis(client, session):
    chunks_anlegen(session, ["x"])
    r = client.get("/suche", params={"q": "x", "modus": "semantisch"})
    assert r.status_code == 200
    assert "vfm embed" in r.text and "hinweis-box" in r.text


@respx.mock
def test_suche_semantisch_zeigt_ergebnis(client, session):
    c, = chunks_anlegen(session, ["Inhalt eins"])
    session.add(Embedding(chunk_id=c.id, modell="embed-m", vektor=[1.0, 0.0]))
    session.commit()
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    )
    r = client.get("/suche", params={"q": "x", "modus": "semantisch"})
    assert "Inhalt eins" in r.text


@respx.mock
def test_antwort_endpoint(client, session):
    c, = chunks_anlegen(session, ["Inhalt <script>"])
    session.add(Embedding(chunk_id=c.id, modell="embed-m", vektor=[1.0, 0.0]))
    session.commit()
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    )
    respx.post("http://chat/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Siehe [1] <img src=x>"}}]})
    )
    r = client.post("/suche/antwort", json={"frage": "Was?"})
    daten = r.json()
    assert r.status_code == 200
    assert daten["quellen"][0]["nummer"] == 1 and daten["quellen"][0]["dateiname"] == "s1.txt"
    assert f'<a href="/dokumente/{daten["quellen"][0]["dokument_id"]}">[1]</a>' in daten["text_html"]
    assert "<img" not in daten["text_html"] and "&lt;img" in daten["text_html"]


def test_antwort_endpoint_ohne_embeddings(client, session):
    chunks_anlegen(session, ["x"])
    r = client.post("/suche/antwort", json={"frage": "Was?"})
    assert r.status_code == 200 and "vfm embed" in r.json()["fehler"]
