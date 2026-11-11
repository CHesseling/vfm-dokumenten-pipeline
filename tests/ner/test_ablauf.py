import pytest

import app.ner.ablauf as ablauf
from app.config import Settings
from app.enums import DokumentTyp, ExtraktionsMethode, LaufStatus, NerMethode
from app.ner.ablauf import ner_ausfuehren, vergleich
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
        ner_ausfuehren(session, s, {NerMethode.MUSTER})
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
    ner_ausfuehren(session, s, {NerMethode.MUSTER, NerMethode.LLM}, labels=["iban"])
    zeilen = vergleich(session, e.id)
    assert len(zeilen) == 1
    assert zeilen[0].label == "iban" and zeilen[0].methoden == {"muster", "llm"}
    lauf = session.query(Lauf).filter_by(schritt="ner:llm").one()
    assert lauf.modell == "chat-m" and lauf.roh_output == {"verworfen": 0}


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
