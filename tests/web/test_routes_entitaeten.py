import app.web.routes_entitaeten as re_
from app.enums import DokumentTyp, ExtraktionsMethode, NerMethode
from app.models import Dokument, Entitaet, TextExtraktion
from app.ner.labels import LabelWunsch, labels_parsen
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
