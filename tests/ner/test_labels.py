import pytest

from app.ner.labels import LabelWunsch, labels_als_text, labels_parsen, schwelle_pruefen
from app.ner.treffer import LABELS


def test_parsen_mit_begriff_und_normalisierung():
    assert labels_parsen(" Person , Aktenzeichen = file number,behörde, person") == [
        LabelWunsch("person"),
        LabelWunsch("aktenzeichen", "file number"),
        LabelWunsch("behörde"),
    ]


def test_leer_heisst_standard():
    assert labels_parsen("") is None
    assert labels_parsen(" , ") is None
    assert labels_parsen(None) is None


@pytest.mark.parametrize(
    "eingabe",
    ["a=b=c", "<script>", "x" * 41, ",".join(f"l{i}" for i in range(21)), "ok=<b>", "=file number"],
)
def test_ungueltig(eingabe):
    with pytest.raises(ValueError):
        labels_parsen(eingabe)


def test_als_text_rundreise():
    labels = labels_parsen("person, aktenzeichen=file number")
    assert labels_als_text(labels) == "person, aktenzeichen=file number"
    assert labels_parsen(labels_als_text(labels)) == labels
    assert labels_als_text(None) == ", ".join(LABELS)


@pytest.mark.parametrize("wert,ok", [(0.05, True), (0.95, True), (0.5, True), (0.0, False), (1.5, False)])
def test_schwelle_pruefen(wert, ok):
    if ok:
        assert schwelle_pruefen(wert) == wert
    else:
        with pytest.raises(ValueError):
            schwelle_pruefen(wert)
