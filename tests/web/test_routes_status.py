import httpx
import pytest
import respx

import app.web.routes_status as rs
from app import progress
from app.enums import DokumentTyp, ExtraktionsMethode
from app.models import Chunk, Dokument, Embedding, TextExtraktion
from app.web import routes_upload


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    monkeypatch.setattr(routes_upload, "_starte_thread", lambda ziel, *a: ziel(*a))
    routes_upload._laeufe_aktiv.clear()


def test_status_seite(client):
    html = client.get("/status").text
    assert "chat-m" in html and "http://chat/v1" in html and "embed-m" in html
    assert "Verbindung prüfen" in html and "NER für alle" in html
    assert "Embeddings erzeugen" in html and "Analyse für alle" in html
    assert "CLI" in html  # Hinweis: CLI-Läufe erscheinen hier nicht
    assert "pdf" in html  # Zählerstände


def test_key_maskiert(client, einstellungen):
    einstellungen.chat_api_key = "sk-supergeheim-1234"
    einstellungen.embed_api_key = None
    html = client.get("/status").text
    assert "sk-supergeheim-1234" not in html and "supergeheim" not in html
    assert "sk-s…" in html and "–" in html


def test_maskiere_key():
    assert rs.maskiere_key("abcdefgh") == "abcd…"
    assert rs.maskiere_key(None) == "–"
    assert rs.maskiere_key("") == "–"


@respx.mock
def test_check_button(client):
    respx.post("http://chat/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    )
    respx.post("http://embed/v1/embeddings").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))
    r = client.post("/status/check")
    assert r.status_code == 200
    assert "Antwort: OK" in r.text and "nicht erreichbar" in r.text
    assert "embed" in r.text and "transcribe" in r.text


@respx.mock
def test_embed_lauf_startet(client, session):
    d = Dokument(sha256="a", dateiname="a.txt", typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    e = TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text="Hallo", ist_aktiv=True)
    session.add(e)
    session.flush()
    session.add(Chunk(textextraktion_id=e.id, position=0, start=0, ende=5, text="Hallo"))
    session.commit()
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
    )
    r = client.post("/status/embed")
    assert r.status_code == 303 and r.headers["location"] == "/laeufe/embed"
    daten = client.get("/laeufe/embed/daten").json()
    assert daten["fertig"] is True and daten["fehler"] is None
    assert daten["erledigt"] == daten["gesamt"] == 1
    session.expire_all()
    assert len(session.query(Embedding).all()) == 1


def test_ner_und_analyse_lauf(client, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(rs, "ner_ausfuehren", lambda *a, **k: aufrufe.append("ner"))
    monkeypatch.setattr(rs, "analyse_ausfuehren", lambda *a, **k: aufrufe.append("analyse"))
    assert client.post("/status/ner").headers["location"] == "/laeufe/ner"
    assert client.post("/status/analyse").headers["location"] == "/laeufe/analyse"
    assert aufrufe == ["ner", "analyse"]
    assert client.get("/laeufe/ner/daten").json()["fertig"] is True


def test_lauf_fehler_wird_gemeldet(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(rs, "ner_ausfuehren", boom)
    client.post("/status/ner")
    assert client.get("/laeufe/ner/daten").json()["fehler"] == "kaputt"
    # danach ist der Schluessel wieder frei
    assert routes_upload.lauf_starten("ner", lambda s, b, a: None) is True


def test_doppelter_lauf_abgelehnt():
    ergebnisse = []

    def lauf(session, bei_fortschritt, soll_abbrechen):
        # synchroner Thread-Ersatz: waehrend der erste Lauf "aktiv" ist, wird der zweite abgelehnt
        ergebnisse.append(routes_upload.lauf_starten("embed", lambda s, b, a: None))

    assert routes_upload.lauf_starten("embed", lauf) is True
    assert ergebnisse == [False]
    assert routes_upload.lauf_starten("embed", lambda s, b, a: None) is True  # nach Ende wieder frei


def test_fortschritt_und_abbruch(client):
    def lauf(session, bei_fortschritt, soll_abbrechen):
        bei_fortschritt(2, 4, "b.txt")
        progress.abbruch_anfordern("ner")
        assert soll_abbrechen() is True

    routes_upload.lauf_starten("ner", lauf)
    d = client.get("/laeufe/ner/daten").json()
    assert d["gesamt"] == 4 and "b.txt" in d["schritt"] or any("b.txt" in v["text"] for v in d["verlauf"])


def test_url_ohne_zugangsdaten(client, einstellungen):
    einstellungen.chat_base_url = "https://user:geheimpass@host.example:8443/v1"
    html = client.get("/status").text
    assert "geheimpass" not in html and "user:" not in html
    assert "https://host.example:8443/v1" in html


def test_start_fehler_beendet_lauf(monkeypatch):
    def boom(*a):
        raise RuntimeError("kein Thread")

    monkeypatch.setattr(routes_upload, "_starte_thread", boom)
    with pytest.raises(RuntimeError):
        routes_upload.lauf_starten("ner", lambda s, b, a: None)
    status = progress.lesen("ner")
    assert status.fertig is True and status.fehler == "kein Thread"
    assert "ner" not in routes_upload._laeufe_aktiv


def test_fehler_lauf_ohne_zugangsdaten_im_html(client, session):
    from app.enums import DokumentTyp, LaufStatus
    from app.models import Dokument, Lauf
    from app.providers.llm_client import ProviderFehler

    d = Dokument(sha256="z", dateiname="z.txt", typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    fehler = ProviderFehler("chat", "https://user:geheim@host/v1", "m", "nicht erreichbar")
    session.add(Lauf(schritt="analyse:zusammenfassung", dokument_id=d.id, provider="x",
                     status=LaufStatus.FEHLER, fehler=f"ProviderFehler: {fehler}"))
    session.commit()
    html = client.get(f"/dokumente/{d.id}").text
    assert "nicht erreichbar" in html and "geheim" not in html


@respx.mock
def test_analyse_lauf_meldet_fehlgeschlagene(client, session):
    d = Dokument(sha256="f", dateiname="f.txt", typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    session.add(TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text="Inhalt", ist_aktiv=True))
    session.commit()
    respx.post("http://chat/v1/chat/completions").mock(return_value=httpx.Response(404))
    client.post("/status/analyse")
    daten = client.get("/laeufe/analyse/daten").json()
    assert daten["fertig"] is True
    assert daten["fehlgeschlagen"] > 0
    assert "Fehler" in daten["schritt"] and "Läufe-Tabelle" in daten["schritt"]


def test_classify_rolle_in_konfiguration(client, einstellungen):
    einstellungen.cortecs_api_key = "ck-geheim-9999"
    html = client.get("/status").text
    assert "classify" in html and "clef-flash:latest" in html and "https://api.cortecs.ai/v1" in html
    assert "ck-geheim-9999" not in html
