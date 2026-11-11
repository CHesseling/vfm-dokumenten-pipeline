import pytest
from sqlmodel import select

from app.models import Dokument, TextExtraktion
from app.web import routes_upload
from tests.fixtures.pdf_bauen import mini_pdf


@pytest.fixture(autouse=True)
def synchron(monkeypatch):
    monkeypatch.setattr(routes_upload, "_starte_thread", lambda ziel, *a: ziel(*a))


def test_upload_formular(client):
    html = client.get("/upload").text
    assert 'name="datei"' in html and 'name="methode"' in html


def test_upload_startet_lauf(client, session):
    pdf = mini_pdf([["Hallo Upload " * 30]])
    antwort = client.post(
        "/upload",
        files=[("datei", ("a.pdf", pdf, "application/pdf")), ("datei", ("b.txt", b"hi", "text/plain"))],
        data={"methode": "schnell"},
    )
    assert antwort.status_code == 303
    ort = antwort.headers["location"]
    assert ort.startswith("/laeufe/upload:")
    daten = client.get(ort + "/daten").json()
    assert daten["fertig"] is True
    assert daten["erledigt"] == daten["gesamt"] == 2
    assert daten["fehler"] is None
    session.expire_all()
    namen = {d.dateiname for d in session.exec(select(Dokument)).all()}
    assert namen == {"a.pdf", "b.txt"}
    assert session.exec(select(TextExtraktion)).all()
    assert client.get(ort).status_code == 200


def test_upload_unbekannte_methode(client):
    antwort = client.post(
        "/upload", files=[("datei", ("a.txt", b"x", "text/plain"))], data={"methode": "magie"}
    )
    assert antwort.status_code == 400


def test_ordner_import(client, session, einstellungen, tmp_path):
    ordner = tmp_path / "material"
    ordner.mkdir()
    (ordner / "notiz.txt").write_text("Hallo Ordner")
    antwort = client.post("/upload/ordner", data={"methode": "schnell"})
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/laeufe/ordner"
    daten = client.get("/laeufe/ordner/daten").json()
    assert daten["fertig"] is True and daten["fehler"] is None
    session.expire_all()
    assert [d.dateiname for d in session.exec(select(Dokument)).all()] == ["notiz.txt"]
    assert not routes_upload._ordner_lock.locked()


def test_zweiter_ordnerlauf_abgelehnt(client):
    assert routes_upload._ordner_lock.acquire(blocking=False)
    try:
        antwort = client.post("/upload/ordner", data={"methode": "schnell"})
    finally:
        routes_upload._ordner_lock.release()
    assert antwort.status_code == 409
    assert "läuft bereits" in antwort.text


def test_lauf_unbekannt(client):
    assert client.get("/laeufe/gibtsnicht/daten").json()["gestartet"] is False


def test_abbrechen(client):
    antwort = client.post("/laeufe/gibtsnicht/abbrechen")
    assert antwort.status_code == 303


def test_upload_thread_fehler_wird_gemeldet(client, monkeypatch):
    def kaputt(s):
        raise RuntimeError("Clients kaputt")

    monkeypatch.setattr(routes_upload, "ingest_clients", kaputt)
    antwort = client.post("/upload", files=[("datei", ("a.txt", b"x", "text/plain"))])
    daten = client.get(antwort.headers["location"] + "/daten").json()
    assert daten["fertig"] is True
    assert "Clients kaputt" in daten["fehler"]


def test_ordner_thread_fehler_gibt_lock_frei(client, monkeypatch):
    def kaputt(*a, **kw):
        raise RuntimeError("Ordner kaputt")

    monkeypatch.setattr(routes_upload, "ingest_ordner", kaputt)
    assert client.post("/upload/ordner", data={"methode": "schnell"}).status_code == 303
    daten = client.get("/laeufe/ordner/daten").json()
    assert daten["fertig"] is True
    assert "Ordner kaputt" in daten["fehler"]
    assert not routes_upload._ordner_lock.locked()
    assert client.post("/upload/ordner", data={"methode": "schnell"}).status_code == 303


def test_upload_abbruch_zwischen_dateien(client, session, monkeypatch):
    from types import SimpleNamespace

    from app import progress

    monkeypatch.setattr(routes_upload, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="fest")))
    echt = routes_upload.ingest_datei_mit_ergebnis
    aufrufe = []

    def mit_abbruch(*a, **kw):
        aufrufe.append(a[2])
        ergebnis = echt(*a, **kw)
        progress.abbruch_anfordern("upload:fest")
        return ergebnis

    monkeypatch.setattr(routes_upload, "ingest_datei_mit_ergebnis", mit_abbruch)
    antwort = client.post(
        "/upload",
        files=[("datei", ("a.txt", b"eins", "text/plain")), ("datei", ("b.txt", b"zwei", "text/plain"))],
    )
    daten = client.get(antwort.headers["location"] + "/daten").json()
    assert aufrufe == ["a.txt"]
    assert daten["fertig"] is True and daten["fehler"] is None
    assert daten["erledigt"] == 1 and daten["gesamt"] == 2
    assert "Abgebrochen nach 1 von 2" in daten["schritt"]
