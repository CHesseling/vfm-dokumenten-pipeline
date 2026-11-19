import pytest
from sqlmodel import select

import app.web.routes_entitaeten as re_
from app.enums import DokumentTyp, ExtraktionsMethode, NerMethode
from app.models import Dokument, Entitaet, TextExtraktion
from app.ner.labels import labels_parsen
from app.providers.llm_client import ProviderFehler
from app.web.routes_entitaeten import markierungen

IBAN = "DE89 3704 0044 0532 0130 00"


def _dok(session, name, text, ents, sha):
    d = Dokument(sha256=sha, dateiname=name, typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    e = TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text=text, ist_aktiv=True)
    session.add(e)
    session.flush()
    for methode, label, t, start in ents:
        session.add(Entitaet(textextraktion_id=e.id, methode=methode, label=label, text=t,
                             start=start, ende=start + len(t)))
    session.commit()
    return d, e


def test_entitaeten_seite_gruppiert(client, session):
    _dok(session, "a.txt", "Anna Meier", [(NerMethode.GLINER, "person", "Anna Meier", 0)], "1")
    _dok(session, "b.txt", "anna meier", [(NerMethode.LLM, "person", "anna meier", 0)], "2")
    html = client.get("/entitaeten").text
    assert html.count("<td>2</td>") == 1  # eine Gruppe mit Anzahl 2
    assert "a.txt" in html and "b.txt" in html
    assert "person" in html
    assert "anna meier" not in client.get("/entitaeten?q=zzz").text.lower()
    assert "anna meier" in client.get("/entitaeten?label=person&q=MEIER").text.lower()
    assert "anna meier" not in client.get("/entitaeten?label=ort").text.lower()
    assert "b.txt" not in client.get("/entitaeten?methode=gliner").text


def test_markierung_im_detail(client, session):
    d, _ = _dok(session, "a.txt", f"Konto <b>{IBAN}</b>", [(NerMethode.MUSTER, "iban", IBAN, 9)], "1")
    html = client.get(f"/dokumente/{d.id}").text
    assert '<mark class="ent-iban"' in html
    assert "&lt;b&gt;" in html and "<b>" not in html
    assert "NER starten" in html


def test_markierungen_laengerer_gewinnt():
    class E:
        def __init__(self, label, text, start):
            self.label, self.text, self.start, self.ende = label, text, start, start + len(text)

    seg = markierungen("Siemens AG Berlin", [E("organisation", "Siemens", 0), E("organisation", "Siemens AG", 0)])
    assert seg[0] == ("Siemens AG", "organisation") and seg[1] == (" Berlin", None)


def test_ner_starten_redirect(client, session, monkeypatch):
    d, e = _dok(session, "a.txt", f"Konto {IBAN}", [], "1")
    monkeypatch.setattr(re_, "chat_client", lambda s: None, raising=False)
    r = client.post(f"/dokumente/{d.id}/ner", data={"methode": ["muster"]})
    assert r.status_code == 303 and r.headers["location"] == f"/dokumente/{d.id}"
    assert "ent-iban" in client.get(f"/dokumente/{d.id}").text


def test_ner_einzel_button_rechnet_neu(client, session, monkeypatch):
    from app.ner.ablauf import NerBilanz

    d, _ = _dok(session, "a.txt", "x", [], "1")
    kwargs = []
    monkeypatch.setattr(re_, "ner_ausfuehren", lambda *a, **k: kwargs.append(k) or NerBilanz())
    client.post(f"/dokumente/{d.id}/ner", data={"methode": ["muster"]})
    assert kwargs[0]["nur_fehlende"] is False


def test_ner_starten_providerfehler(client, session, monkeypatch):
    d, _ = _dok(session, "a.txt", "x", [], "1")

    def boom(*a, **k):
        raise ProviderFehler("chat", "http://x", "m", "nicht erreichbar")

    monkeypatch.setattr(re_, "ner_ausfuehren", boom)
    r = client.post(f"/dokumente/{d.id}/ner", data={"methode": ["llm"]})
    assert r.status_code == 303
    seite = client.get(r.headers["location"])
    assert seite.status_code == 200 and "fehlgeschlagen" in seite.text and "Läufe" in seite.text
    assert "nicht erreichbar" not in seite.text.split("<h2>Läufe</h2>")[0]
    assert "ner" in seite.text.split("<h2>Läufe</h2>")[1] and "nicht erreichbar" in seite.text.split("<h2>Läufe</h2>")[1]


def test_ner_starten_unbekannt_404(client):
    assert client.post("/dokumente/99999/ner").status_code == 404


def test_gleiche_iban_ueber_methoden_eine_zeile(client, session, monkeypatch):
    import app.ner.ablauf as ablauf
    from app.ner.llm_ner import LlmEntitaeten, LlmEntitaet

    class Fake:
        def chat_json(self, m, schema):
            return LlmEntitaeten(entitaeten=[LlmEntitaet(label="iban", text=IBAN)])

    d, _ = _dok(session, "a.txt", f"Konto {IBAN} bitte.", [], "1")
    monkeypatch.setattr(ablauf, "chat_client", lambda s: Fake())
    from app.config import Settings
    from tests.conftest import TEST_DATABASE_URL
    s = Settings(database_url=TEST_DATABASE_URL, chat_base_url="http://c/v1", chat_model="m",
                 embed_base_url="http://e/v1", embed_model="e", _env_file=None)
    ablauf.ner_ausfuehren(session, s, {NerMethode.MUSTER, NerMethode.LLM}, labels=labels_parsen("iban"))
    html = client.get("/entitaeten?label=iban").text
    assert html.count("<tr><td>") == 1 and "<td>2</td>" in html


def test_ner_formular_reicht_parameter_durch(client, session, monkeypatch):
    from app.ner.ablauf import NerBilanz

    d, _ = _dok(session, "a.txt", "Text", [], "1")
    erhalten = {}

    def fake(session, s, methoden, **kw):
        erhalten.update(kw, methoden=methoden)
        return NerBilanz()

    monkeypatch.setattr(re_, "ner_ausfuehren", fake)
    r = client.post(f"/dokumente/{d.id}/ner", data={"methode": ["gliner"], "labels": "person, aktenzeichen=file number",
                                                    "schwelle": "0.3"})
    assert r.status_code == 303 and r.headers["location"] == f"/dokumente/{d.id}"
    assert erhalten["schwelle"] == 0.3 and erhalten["methoden"] == {NerMethode.GLINER}
    assert erhalten["labels"] == labels_parsen("person, aktenzeichen=file number")


def test_ner_formular_leere_felder_heisst_standard(client, session, monkeypatch):
    from app.ner.ablauf import NerBilanz

    d, _ = _dok(session, "a.txt", "Text", [], "1")
    erhalten = {}
    monkeypatch.setattr(re_, "ner_ausfuehren", lambda session, s, m, **kw: erhalten.update(kw) or NerBilanz())
    client.post(f"/dokumente/{d.id}/ner", data={"methode": ["muster"], "labels": "", "schwelle": ""})
    assert erhalten["labels"] is None and erhalten["schwelle"] is None


@pytest.mark.parametrize("daten", [{"labels": "a=b=c"}, {"schwelle": "1.5"}, {"schwelle": "abc"},
                                   {"labels": "<script>"}, {"schwelle": "nan"}])
def test_ner_formular_ungueltig(client, session, monkeypatch, daten):
    d, _ = _dok(session, "a.txt", "Text", [], "1")
    monkeypatch.setattr(re_, "ner_ausfuehren", lambda *a, **k: pytest.fail("darf nicht laufen"))
    r = client.post(f"/dokumente/{d.id}/ner", data={"methode": ["muster"], **daten})
    assert r.status_code == 303 and r.headers["location"].endswith("?parameter_fehler=1")
    seite = client.get(r.headers["location"]).text
    normal = client.get(f"/dokumente/{d.id}").text
    assert "Ungültige Labels oder Schwelle" in seite and "Ungültige Labels" not in normal
    assert seite.count("<script>") == normal.count("<script>") and "&lt;script&gt;" not in seite


def test_parameter_ueber_treffern(client, session):
    from app.enums import LaufStatus
    from app.models import Lauf

    d, e = _dok(session, "a.txt", "Anna Meier", [(NerMethode.GLINER, "person", "Anna Meier", 0)], "1")
    session.add(Lauf(schritt="ner:gliner", dokument_id=d.id, provider="ollama", status=LaufStatus.ERFOLG,
                     roh_output={"extraktion_id": e.id, "schwelle": 0.3, "labels": "person, behörde"}))
    session.commit()
    assert "Schwelle 0.3 · Labels: person, behörde" in client.get(f"/dokumente/{d.id}").text


def test_eigenes_label_markiert_neutral(client, session):
    d, _ = _dok(session, "a.txt", "AZ 12 liegt vor", [(NerMethode.LLM, "aktenzeichen nr", "AZ 12", 0)], "1")
    html = client.get(f"/dokumente/{d.id}").text
    assert '<mark class="ent-eigen" title="aktenzeichen nr (llm)">AZ 12</mark>' in html


def test_entitaeten_loeschen_route(client, session):
    d, e = _dok(session, "a.txt", f"Konto {IBAN}", [(NerMethode.MUSTER, "iban", IBAN, 6),
                                                    (NerMethode.LLM, "iban", IBAN, 6)], "1")
    r = client.post(f"/dokumente/{d.id}/entitaeten/loeschen", data={"methode": "llm"})
    assert r.status_code == 303 and r.headers["location"] == f"/dokumente/{d.id}"
    assert [x.methode for x in session.exec(select(Entitaet)).all()] == [NerMethode.MUSTER]
    assert client.post(f"/dokumente/{d.id}/entitaeten/loeschen", data={"methode": "quatsch"}).status_code == 400
    client.post(f"/dokumente/{d.id}/entitaeten/loeschen", data={"methode": "alle"})
    assert session.exec(select(Entitaet)).all() == []
    assert client.post("/dokumente/99999/entitaeten/loeschen", data={"methode": "alle"}).status_code == 404


def test_entitaeten_seite_zeigt_eigene_labels(client, session):
    _dok(session, "a.txt", "AZ 12", [(NerMethode.LLM, "aktenzeichen", "AZ 12", 0)], "1")
    _dok(session, "b.txt", "Anna", [(NerMethode.GLINER, "person", "Anna", 0)], "2")
    assert '<option value="aktenzeichen"' in client.get("/entitaeten").text
    gefiltert = client.get("/entitaeten?label=aktenzeichen").text
    assert "AZ 12" in gefiltert and "b.txt" not in gefiltert
