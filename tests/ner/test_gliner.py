import re

import pytest

import app.ner.gliner as gl
from app.ner.gliner import GLINER_LABELS, GlinerNer


class FakeModell:
    """Meldet jedes Vorkommen von 'Müller' als person, mit Offsets im Fenster."""

    def __init__(self):
        self.aufrufe = []

    def extract_entities(self, text, labels, threshold=0.5, include_spans=False, include_confidence=False):
        self.aufrufe.append((text, list(labels), threshold))
        treffer = [
            {"text": m.group(), "confidence": 0.9, "start": m.start(), "end": m.end()}
            for m in re.finditer("Müller", text)
        ]
        return {"entities": {"person": treffer}}


@pytest.fixture
def fake(monkeypatch):
    f = FakeModell()
    monkeypatch.setattr(gl, "_MODELLE", {})
    monkeypatch.setattr(gl, "_lade_modell", lambda name: f)
    return f


def _text_mit_mueller(pos, laenge=3000):
    wort = "wort "
    text = (wort * (laenge // len(wort) + 1))[:laenge]
    return text[:pos] + "Müller" + text[pos + 6 :]


def test_offsets_ueber_fenster(fake):
    text = _text_mit_mueller(2500)
    treffer = GlinerNer("m").finde(text)
    assert [t.start for t in treffer] == [2500]
    assert text[treffer[0].start : treffer[0].ende] == "Müller"
    assert len(fake.aufrufe) > 1  # wirklich gefenstert


def test_keine_duplikate_aus_ueberlappung(fake):
    # Position in der Ueberlappung zweier Fenster (1100..1200)
    text = _text_mit_mueller(1130)
    treffer = GlinerNer("m").finde(text)
    assert len(treffer) == 1 and treffer[0].start == 1130


def test_labels_werden_uebersetzt(fake):
    GlinerNer("m").finde("Müller", ["organisation", "ort", "iban"])
    assert fake.aufrufe[0][1] == ["company", "location"]  # iban ist kein GliNER-Label


def test_ergebnis_label_intern(fake):
    t = GlinerNer("m").finde("Herr Müller kam.", ["person"])[0]
    assert t.label == "person" and t.score == 0.9


def test_schwelle_wird_uebergeben(fake):
    GlinerNer("m", schwelle=0.7).finde("Müller")
    assert fake.aufrufe[0][2] == 0.7


def test_keine_gliner_labels_kein_aufruf(fake):
    assert GlinerNer("m").finde("Müller", ["iban"]) == []
    assert fake.aufrufe == []


@pytest.mark.modelle
def test_gliner_deutsch():
    treffer = GlinerNer("fastino/gliner2-base-v1").finde("Angela Merkel traf in Berlin Vertreter der Siemens AG.")
    labels = {t.label for t in treffer}
    assert {"person", "ort", "organisation"} <= labels


def test_abgeschnittener_span_am_fensterrand(monkeypatch):
    text = ("wort " * 238) + "Siemens AG " + ("wort " * 200)  # "Siemens" endet bei Fenstergrenze
    pos = text.index("Siemens")

    class Fake:
        def extract_entities(self, teil, labels, **k):
            i = teil.find("Siemens")
            if i < 0:
                return {"entities": {}}
            ende = min(i + 10, len(teil))
            wort = teil[i:ende]
            return {"entities": {"company": [{"text": wort, "confidence": 0.9, "start": i, "end": ende}]}}

    monkeypatch.setattr(gl, "_MODELLE", {})
    monkeypatch.setattr(gl, "_lade_modell", lambda name: Fake())
    treffer = GlinerNer("m").finde(text, ["organisation"])
    assert len(treffer) == 1 and treffer[0].start == pos
