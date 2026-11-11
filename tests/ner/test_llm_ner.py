from app.ner.llm_ner import LlmEntitaeten, LlmEntitaet, llm_ner


class FakeClient:
    def __init__(self, *entitaeten):
        self.antwort = LlmEntitaeten(entitaeten=[LlmEntitaet(label=l, text=t) for l, t in entitaeten])
        self.aufrufe = 0

    def chat_json(self, messages, schema):
        self.aufrufe += 1
        assert schema is LlmEntitaeten
        return self.antwort


def test_halluzination_wird_verworfen():
    stat = {}
    treffer = llm_ner(FakeClient(("person", "Hans Wurst")), "Frau Meier kam.", ["person"], stat)
    assert treffer == [] and stat["verworfen"] == 1


def test_alle_vorkommen():
    text = "Anna Meier traf Bob. Später rief Anna Meier an."
    treffer = llm_ner(FakeClient(("person", "Anna Meier")), text, ["person"])
    assert [t.start for t in treffer] == [0, text.rindex("Anna Meier")]
    assert all(text[t.start : t.ende] == "Anna Meier" for t in treffer)


def test_fremdes_label_verworfen():
    stat = {}
    treffer = llm_ner(FakeClient(("tier", "Bob"), ("person", "Bob")), "Bob kam.", ["person"], stat)
    assert [t.label for t in treffer] == ["person"] and stat["verworfen"] == 1


def test_langer_text_wird_gefenstert():
    client = FakeClient(("person", "Bob"))
    llm_ner(client, "Bob " + "wort " * 3000, ["person"])
    assert client.aufrufe >= 3


def test_wortgrenzen_bei_offsets():
    text = "Lieferung an Li Wei"
    treffer = llm_ner(FakeClient(("person", "Li")), text, ["person"])
    assert [t.start for t in treffer] == [text.index("Li Wei")]
