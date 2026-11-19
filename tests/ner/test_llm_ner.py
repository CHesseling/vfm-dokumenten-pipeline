from app.ner.labels import LabelWunsch
from app.ner.llm_ner import LlmEntitaeten, LlmEntitaet, llm_ner

P = [LabelWunsch("person")]


class FakeClient:
    def __init__(self, *entitaeten):
        self.antwort = LlmEntitaeten(entitaeten=[LlmEntitaet(label=l, text=t) for l, t in entitaeten])
        self.aufrufe = 0

    def chat_json(self, messages, schema):
        self.aufrufe += 1
        self.nachrichten = messages
        assert schema is LlmEntitaeten
        return self.antwort


def test_halluzination_wird_verworfen():
    stat = {}
    treffer = llm_ner(FakeClient(("person", "Hans Wurst")), "Frau Meier kam.", P, stat)
    assert treffer == [] and stat["verworfen"] == 1


def test_alle_vorkommen():
    text = "Anna Meier traf Bob. Später rief Anna Meier an."
    treffer = llm_ner(FakeClient(("person", "Anna Meier")), text, P)
    assert [t.start for t in treffer] == [0, text.rindex("Anna Meier")]
    assert all(text[t.start : t.ende] == "Anna Meier" for t in treffer)


def test_fremdes_label_verworfen():
    stat = {}
    treffer = llm_ner(FakeClient(("tier", "Bob"), ("person", "Bob")), "Bob kam.", P, stat)
    assert [t.label for t in treffer] == ["person"] and stat["verworfen"] == 1


def test_langer_text_wird_gefenstert():
    client = FakeClient(("person", "Bob"))
    llm_ner(client, "Bob " + "wort " * 3000, P)
    assert client.aufrufe >= 3


def test_wortgrenzen_bei_offsets():
    text = "Lieferung an Li Wei"
    treffer = llm_ner(FakeClient(("person", "Li")), text, P)
    assert [t.start for t in treffer] == [text.index("Li Wei")]


def test_eigenes_label_im_prompt_und_treffer():
    client = FakeClient(("aktenzeichen", "AZ 12/34"))
    treffer = llm_ner(client, "Siehe AZ 12/34.", [LabelWunsch("aktenzeichen", "file number")])
    assert [(t.label, t.text) for t in treffer] == [("aktenzeichen", "AZ 12/34")]
    assert "- aktenzeichen: file number" in client.nachrichten[0]["content"]


def test_bekanntes_label_behaelt_erklaerung():
    client = FakeClient()
    llm_ner(client, "Text.", [LabelWunsch("person")])
    assert "- person: Namen von Personen" in client.nachrichten[0]["content"]


def test_label_gross_geschrieben_wird_angenommen():
    treffer = llm_ner(FakeClient(("Behörde ", "Stadtamt")), "Das Stadtamt schrieb.", [LabelWunsch("behörde")])
    assert [(t.label, t.text) for t in treffer] == [("behörde", "Stadtamt")]
