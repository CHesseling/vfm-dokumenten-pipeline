import pytest

import app.ner.ablauf as ablauf
from app.config import Settings
from app.enums import DokumentTyp, ExtraktionsMethode, LaufStatus, NerMethode
from app.ner.ablauf import entitaeten_loeschen, ner_ausfuehren, vergleich
from app.ner.labels import LabelWunsch, labels_parsen
from app.ner.llm_ner import LlmEntitaeten, LlmEntitaet
from app.models import Dokument, Entitaet, Lauf, TextExtraktion
from tests.conftest import TEST_DATABASE_URL

IBAN = "DE89 3704 0044 0532 0130 00"


@pytest.fixture
def s():
    return Settings(database_url=TEST_DATABASE_URL, chat_base_url="http://chat/v1", chat_model="chat-m",
                    embed_base_url="http://e/v1", embed_model="e", _env_file=None)


def _extraktion(session, text, name="a.txt", sha="x"):
    d = Dokument(sha256=sha, dateiname=name, typ=DokumentTyp.TEXT, mime="text/plain", groesse=len(text))
    session.add(d)
    session.flush()
    e = TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text=text, ist_aktiv=True)
    session.add(e)
    session.commit()
    return d, e


class FakeLlm:
    def chat_json(self, messages, schema):
        return LlmEntitaeten(entitaeten=[LlmEntitaet(label="iban", text=IBAN)])


def test_ner_ersetzt_alte_entitaeten(session, s):
    _, e = _extraktion(session, f"Konto {IBAN} bitte.")
    for _ in range(2):
        ner_ausfuehren(session, s, {NerMethode.MUSTER}, nur_fehlende=False)
    ents = session.query(Entitaet).filter_by(textextraktion_id=e.id).all()
    assert len([x for x in ents if x.label == "iban"]) == 1
    laeufe = session.query(Lauf).filter_by(schritt="ner:muster").all()
    assert len(laeufe) == 2 and all(l.status == LaufStatus.ERFOLG and l.modell is None for l in laeufe)


def test_leerer_text_uebersprungen(session, s):
    _extraktion(session, "   ")
    bilanz = ner_ausfuehren(session, s, {NerMethode.MUSTER})
    assert bilanz.uebersprungen == 1
    assert session.query(Lauf).one().status == LaufStatus.UEBERSPRUNGEN


def test_vergleich_methoden(session, s, monkeypatch):
    _, e = _extraktion(session, f"Konto {IBAN} bitte.")
    monkeypatch.setattr(ablauf, "chat_client", lambda s: FakeLlm())
    ner_ausfuehren(session, s, {NerMethode.MUSTER, NerMethode.LLM}, labels=labels_parsen("iban"))
    zeilen = vergleich(session, e.id)
    assert len(zeilen) == 1
    assert zeilen[0].label == "iban" and zeilen[0].methoden == {"muster", "llm"}
    lauf = session.query(Lauf).filter_by(schritt="ner:llm").one()
    assert lauf.modell == "chat-m" and lauf.roh_output == {"verworfen": 0, "extraktion_id": e.id, "labels": "iban"}


def test_fehler_einer_methode_stoppt_nicht(session, s, monkeypatch):
    _extraktion(session, f"Konto {IBAN} bitte.")

    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(ablauf, "llm_ner", boom)
    bilanz = ner_ausfuehren(session, s, {NerMethode.MUSTER, NerMethode.LLM})
    assert bilanz.fehler == 1 and bilanz.entitaeten >= 1
    assert session.query(Lauf).filter_by(schritt="ner:llm").one().status == LaufStatus.FEHLER


def test_nur_ein_dokument_und_abbruch(session, s):
    d1, _ = _extraktion(session, f"Konto {IBAN}", "a", "1")
    _extraktion(session, f"Konto {IBAN}", "b", "2")
    assert ner_ausfuehren(session, s, {NerMethode.MUSTER}, dokument_id=d1.id).dokumente == 1
    assert ner_ausfuehren(session, s, {NerMethode.MUSTER}, soll_abbrechen=lambda: True).dokumente == 0


def test_ner_zweiter_lauf_ueberspringt_vorhandenes(session, s, monkeypatch):
    _extraktion(session, f"Konto {IBAN} bitte.")
    _extraktion(session, "Hier steht nichts Erkennbares.", name="b.txt", sha="y")
    ner_ausfuehren(session, s, {NerMethode.MUSTER})
    laeufe = session.query(Lauf).count()
    monkeypatch.setattr(ablauf, "finde_muster", lambda *a, **k: pytest.fail("sollte nicht rechnen"))
    bilanz = ner_ausfuehren(session, s, {NerMethode.MUSTER})
    assert bilanz.vorhanden == 2 and bilanz.entitaeten == 0
    assert session.query(Lauf).count() == laeufe  # auch das Dokument ohne Treffer wird nicht neu gerechnet


def test_ner_alle_neu_rechnet_neu(session, s):
    _extraktion(session, f"Konto {IBAN} bitte.")
    ner_ausfuehren(session, s, {NerMethode.MUSTER})
    bilanz = ner_ausfuehren(session, s, {NerMethode.MUSTER}, nur_fehlende=False)
    assert bilanz.entitaeten >= 1 and session.query(Lauf).count() == 2


def test_ner_leerer_text_nur_einmal_protokolliert(session, s):
    _extraktion(session, "   ")
    for _ in range(3):
        ner_ausfuehren(session, s, {NerMethode.MUSTER}, nur_fehlende=False)
    assert session.query(Lauf).filter_by(status=LaufStatus.UEBERSPRUNGEN).count() == 1


class GlinerAufzeichnung:
    aufrufe: list = []

    def __init__(self, modell, schwelle=0.5):
        self.schwelle = schwelle

    def finde(self, text, labels=None):
        GlinerAufzeichnung.aufrufe.append((self.schwelle, labels))
        return []


@pytest.fixture
def gliner_fake(monkeypatch):
    GlinerAufzeichnung.aufrufe = []
    monkeypatch.setattr(ablauf, "GlinerNer", GlinerAufzeichnung)
    return GlinerAufzeichnung


def test_parameter_im_lauf(session, s, gliner_fake):
    _extraktion(session, "Text mit Inhalt.")
    labels = labels_parsen("person, behörde=government agency")
    ner_ausfuehren(session, s, {NerMethode.GLINER}, labels=labels, schwelle=0.3)
    assert gliner_fake.aufrufe == [(0.3, labels)]
    lauf = session.query(Lauf).filter_by(schritt="ner:gliner").one()
    assert lauf.roh_output["schwelle"] == 0.3
    assert lauf.roh_output["labels"] == "person, behörde=government agency"


def test_schwelle_default_aus_settings(session, s, gliner_fake):
    _extraktion(session, "Text mit Inhalt.")
    s.gliner_schwelle = 0.65
    ner_ausfuehren(session, s, {NerMethode.GLINER})
    assert gliner_fake.aufrufe[0][0] == 0.65
    assert session.query(Lauf).one().roh_output["schwelle"] == 0.65


def test_eigene_labels_nicht_normalisiert(session, s, monkeypatch):
    class Fake:
        def chat_json(self, messages, schema):
            return LlmEntitaeten(entitaeten=[LlmEntitaet(label="aktenzeichen", text="AZ 12/34")])

    _, e = _extraktion(session, "Siehe AZ 12/34.")
    monkeypatch.setattr(ablauf, "chat_client", lambda s: Fake())
    ner_ausfuehren(session, s, {NerMethode.LLM, NerMethode.MUSTER}, labels=labels_parsen("aktenzeichen"))
    ent = session.query(Entitaet).one()
    assert ent.label == "aktenzeichen" and ent.normalisiert is None and ent.methode == NerMethode.LLM


def test_loeschen_dann_wieder_fehlend(session, s):
    _, e = _extraktion(session, f"Konto {IBAN} bitte.")
    ner_ausfuehren(session, s, {NerMethode.MUSTER})
    assert entitaeten_loeschen(session, e.id, {NerMethode.MUSTER}, "ollama") == 1
    session.commit()
    assert session.query(Entitaet).count() == 0
    lauf = session.query(Lauf).filter_by(schritt="loeschen:ner:muster").one()
    assert lauf.roh_output == {"extraktion_id": e.id, "geloescht": 1}
    bilanz = ner_ausfuehren(session, s, {NerMethode.MUSTER})  # nur_fehlende=True
    assert bilanz.vorhanden == 0 and session.query(Entitaet).count() == 1
    assert ner_ausfuehren(session, s, {NerMethode.MUSTER}).vorhanden == 1  # danach wieder vorhanden


def test_loeschen_nur_gewaehlte_methode(session, s, monkeypatch):
    _, e = _extraktion(session, f"Konto {IBAN} bitte.")
    monkeypatch.setattr(ablauf, "chat_client", lambda s: FakeLlm())
    ner_ausfuehren(session, s, {NerMethode.MUSTER, NerMethode.LLM})
    entitaeten_loeschen(session, e.id, {NerMethode.LLM}, "ollama")
    session.commit()
    assert [x.methode for x in session.query(Entitaet).all()] == [NerMethode.MUSTER]
    assert ner_ausfuehren(session, s, {NerMethode.MUSTER, NerMethode.LLM}).vorhanden == 1


def test_lauf_mit_null_treffern_bleibt_vorhanden(session, s):
    _extraktion(session, "Hier steht nichts Erkennbares.")
    ner_ausfuehren(session, s, {NerMethode.MUSTER})
    assert ner_ausfuehren(session, s, {NerMethode.MUSTER}).vorhanden == 1


def test_methode_ohne_nutzbare_labels_laesst_treffer_stehen(session, s, gliner_fake):
    _, e = _extraktion(session, f"Konto {IBAN} bitte.")
    ner_ausfuehren(session, s, {NerMethode.MUSTER})
    session.add(Entitaet(textextraktion_id=e.id, methode=NerMethode.GLINER, label="person", text="Konto", start=0, ende=5))
    session.commit()
    bilanz = ner_ausfuehren(session, s, {NerMethode.MUSTER, NerMethode.GLINER}, labels=labels_parsen("aktenzeichen=file number, iban"),
                            nur_fehlende=False)
    # Muster hat "iban" -> laeuft; GliNER hat "aktenzeichen" -> laeuft
    assert bilanz.uebersprungen == 0
    bilanz = ner_ausfuehren(session, s, {NerMethode.MUSTER}, labels=labels_parsen("aktenzeichen"), nur_fehlende=False)
    assert bilanz.uebersprungen == 1
    assert session.query(Entitaet).filter_by(methode=NerMethode.MUSTER).count() == 1  # IBAN bleibt
    bilanz = ner_ausfuehren(session, s, {NerMethode.GLINER}, labels=labels_parsen("iban"), nur_fehlende=False)
    assert bilanz.uebersprungen == 1 and gliner_fake.aufrufe[-1][1] != labels_parsen("iban")
