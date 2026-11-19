import httpx
import pytest
import respx

from app.enums import AnalyseArt, DokumentTyp, ExtraktionsMethode, NerMethode
from app.models import Analyse, Chunk, Dokument, Embedding, Entitaet, TextExtraktion


def _dok(session, name, text, sha, parent_id=None):
    d = Dokument(sha256=sha, dateiname=name, typ=DokumentTyp.TEXT, mime="text/plain", groesse=1,
                 metadaten={"datum": "2026-01-01"}, parent_id=parent_id)
    session.add(d)
    session.flush()
    e = TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text=text, ist_aktiv=True)
    session.add(e)
    session.flush()
    c = Chunk(textextraktion_id=e.id, position=0, start=0, ende=len(text), text=text)
    session.add(c)
    session.commit()
    return d, e, c


def test_suche_volltext(client, session):
    d, _, _ = _dok(session, "a.txt", "Der Kassenbericht zeigt Auffälligkeiten.", "1")
    r = client.get("/api/suche", params={"q": "Kassenbericht", "modus": "volltext"})
    assert r.status_code == 200
    treffer = r.json()
    assert treffer[0]["dokument_id"] == d.id
    assert treffer[0]["dateiname"] == "a.txt" and treffer[0]["typ"] == "text"
    assert "Kassenbericht" in treffer[0]["ausschnitt"] and "<b>" not in treffer[0]["ausschnitt"]
    assert treffer[0]["score"] is None or isinstance(treffer[0]["score"], float)


def test_suche_semantisch(client, session):
    d, _, c = _dok(session, "a.txt", "Rechnung Nr. 5", "1")
    session.add(Embedding(chunk_id=c.id, modell="embed-m", vektor=[1.0, 0.0, 0.0]))
    session.commit()
    with respx.mock:
        respx.post("http://embed/v1/embeddings").mock(
            return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]})
        )
        r = client.get("/api/suche", params={"q": "Rechnung", "top_k": 3})
    assert r.status_code == 200
    assert r.json()[0]["dokument_id"] == d.id
    assert r.json()[0]["score"] == pytest.approx(1.0)


def test_suche_ohne_embeddings_409(client, session):
    _dok(session, "a.txt", "x", "1")
    r = client.get("/api/suche", params={"q": "x"})
    assert r.status_code == 409 and "vfm embed" in r.json()["detail"]


def test_suche_provider_fehler_502(client, session):
    _, _, c = _dok(session, "a.txt", "x", "1")
    session.add(Embedding(chunk_id=c.id, modell="embed-m", vektor=[1.0, 0.0, 0.0]))
    session.commit()
    with respx.mock:
        respx.post("http://embed/v1/embeddings").mock(side_effect=httpx.ConnectError("x"))
        r = client.get("/api/suche", params={"q": "x"})
    assert r.status_code == 502 and "embed" in r.json()["detail"]


def test_suche_top_k_grenze(client):
    assert client.get("/api/suche", params={"q": "x", "top_k": 51}).status_code == 422


def test_dokument_detail(client, session):
    eltern, _, _ = _dok(session, "mail.txt", "Mail", "0")
    d, e, _ = _dok(session, "a.txt", "Anna Meier", "1", parent_id=eltern.id)
    anhang, _, _ = _dok(session, "b.txt", "B", "2", parent_id=d.id)
    session.add(Entitaet(textextraktion_id=e.id, methode=NerMethode.GLINER, label="person", text="Anna Meier", start=0, ende=10))
    session.add(Analyse(dokument_id=d.id, art=AnalyseArt.ZUSAMMENFASSUNG, modell="m", ergebnis={"text": "Kurz."}))
    session.commit()
    r = client.get(f"/api/dokumente/{d.id}")
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == d.id and j["dateiname"] == "a.txt" and j["typ"] == "text"
    assert j["metadaten"] == {"datum": "2026-01-01"}
    assert j["text"] == "Anna Meier" and j["text_gekuerzt"] is False
    assert j["entitaeten"] == [{"label": "person", "text": "Anna Meier", "methode": "gliner"}]
    assert j["analysen"] == {"zusammenfassung": {"text": "Kurz."}}
    assert j["anhaenge"] == [anhang.id] and j["parent_id"] == eltern.id


def test_dokument_404(client):
    r = client.get("/api/dokumente/999")
    assert r.status_code == 404 and r.json() == {"detail": "Dokument nicht gefunden"}


def test_text_gekuerzt(client, session):
    d, _, _ = _dok(session, "gross.txt", "x" * 25000, "1")
    j = client.get(f"/api/dokumente/{d.id}").json()
    assert len(j["text"]) == 20000 and j["text_gekuerzt"] is True


def test_entitaeten(client, session):
    d1, e1, _ = _dok(session, "a.txt", "Anna Meier", "1")
    d2, e2, _ = _dok(session, "b.txt", "anna meier", "2")
    for e, t in ((e1, "Anna Meier"), (e2, "anna meier")):
        session.add(Entitaet(textextraktion_id=e.id, methode=NerMethode.GLINER, label="person", text=t, start=0, ende=10))
    session.add(Entitaet(textextraktion_id=e1.id, methode=NerMethode.MUSTER, label="iban", text="DE89", start=0, ende=4))
    session.commit()
    alle = client.get("/api/entitaeten").json()
    assert {x["label"] for x in alle} == {"person", "iban"}
    person = client.get("/api/entitaeten", params={"label": "person", "q": "MEIER"}).json()
    assert len(person) == 1 and person[0]["anzahl"] == 2
    assert sorted(person[0]["dokument_ids"]) == sorted([d1.id, d2.id])
    assert len(client.get("/api/entitaeten", params={"limit": 1}).json()) == 1


@respx.mock
def test_frage(client, session):
    d, _, c = _dok(session, "a.txt", "Die Summe beträgt 5 Euro.", "1")
    session.add(Embedding(chunk_id=c.id, modell="embed-m", vektor=[1.0, 0.0, 0.0]))
    session.commit()
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]})
    )
    respx.post("http://chat/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Es sind 5 Euro [1]."}}]})
    )
    r = client.post("/api/frage", json={"frage": "Wie viel?"})
    assert r.status_code == 200
    assert r.json() == {"antwort": "Es sind 5 Euro [1].",
                        "quellen": [{"nummer": 1, "dokument_id": d.id, "dateiname": "a.txt"}]}


def test_frage_ohne_embeddings_409(client):
    assert client.post("/api/frage", json={"frage": "x"}).status_code == 409


def test_token_pflicht_wenn_gesetzt(client, einstellungen):
    einstellungen.api_token = "geheim"
    r = client.get("/api/entitaeten")
    assert r.status_code == 401 and r.json() == {"detail": "API-Token fehlt oder falsch"}
    assert client.get("/api/entitaeten", headers={"Authorization": "Bearer falsch"}).status_code == 401
    assert client.get("/api/entitaeten", headers={"Authorization": "Bearer geheim"}).status_code == 200


def test_openapi_enthaelt_beschreibungen(client):
    spec = client.get("/openapi.json").json()
    params = spec["paths"]["/api/suche"]["get"]["parameters"]
    q = next(p for p in params if p["name"] == "q")
    assert q["description"]
    assert spec["paths"]["/api/suche"]["get"]["tags"] == ["agent"]
    schema = spec["components"]["schemas"]["SuchErgebnis"]
    assert all("description" in f for f in schema["properties"].values())
