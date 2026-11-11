from app.ner.muster import finde_muster
from app.ner.treffer import Treffer


def _nach_label(text, label):
    return [t for t in finde_muster(text) if t.label == label]


def test_gueltige_iban_mit_leerzeichen():
    t = _nach_label("Konto: DE89 3704 0044 0532 0130 00 bitte.", "iban")
    assert len(t) == 1
    assert t[0].normalisiert == "DE89370400440532013000"
    assert t[0].text == "DE89 3704 0044 0532 0130 00"
    assert t[0].score == 1.0


def test_ungueltige_iban_wird_verworfen():
    assert _nach_label("DE89 3704 0044 0532 0130 01", "iban") == []


def test_telefon_national():
    t = _nach_label("Rufen Sie an: 040 123456-78", "telefon")
    assert len(t) == 1
    assert t[0].normalisiert == "+494012345678"


def test_email():
    t = _nach_label("Mail an Max.Muster@Example.DE.", "email")
    assert [x.normalisiert for x in t] == ["max.muster@example.de"]


def test_geldbetrag_varianten():
    text = "Zahlung 1.234,50 € sowie EUR 300 und 12 Euro."
    t = _nach_label(text, "geldbetrag")
    assert [x.normalisiert for x in t] == ["1234.50 EUR", "300.00 EUR", "12.00 EUR"]


def test_datum_ausgeschrieben():
    t = _nach_label("Am 3. März 2024 war es so.", "datum")
    assert len(t) == 1 and t[0].normalisiert == "2024-03-03"


def test_datum_varianten():
    t = _nach_label("Am 03.03.2024 und 2024-03-04.", "datum")
    assert [x.normalisiert for x in t] == ["2024-03-03", "2024-03-04"]


def test_datum_unparsbar_bleibt_ohne_normalisierung():
    t = _nach_label("Am 45.13.2024 sonst.", "datum")
    assert len(t) == 1 and t[0].normalisiert is None


def test_offsets_stimmen():
    text = (
        "IBAN DE89 3704 0044 0532 0130 00, Tel 040 123456-78, a@b.de, "
        "1.234,50 € am 3. März 2024."
    )
    treffer = finde_muster(text)
    assert len(treffer) >= 5
    for t in treffer:
        assert text[t.start:t.ende] == t.text


def test_sortiert_und_ueberlappungsfrei():
    treffer = finde_muster("DE89 3704 0044 0532 0130 00 und 12 Euro am 3.3.2024")
    assert [t.start for t in treffer] == sorted(t.start for t in treffer)
    for a, b in zip(treffer, treffer[1:]):
        assert a.ende <= b.start


def test_iban_ist_keine_telefonnummer():
    labels = {t.label for t in finde_muster("IBAN DE89 3704 0044 0532 0130 00")}
    assert "iban" in labels and "telefon" not in labels


def test_datum_und_betrag_sind_keine_telefonnummer():
    labels = {t.label for t in finde_muster("Am 03.03.2024 zahlte er 1.234,50 EUR.")}
    assert "telefon" not in labels


def test_treffer_ist_unveraenderlich():
    t = Treffer("iban", "x", 0, 1)
    assert t.normalisiert is None and t.score is None


def test_normalisiere_wie_finde_muster():
    from app.ner.muster import normalisiere

    assert normalisiere("iban", "DE89 3704 0044 0532 0130 00") == "DE89370400440532013000"
    assert normalisiere("email", "Max@Example.DE") == "max@example.de"
    assert normalisiere("datum", "3. März 2024") == "2024-03-03"
    assert normalisiere("geldbetrag", "1.234,50 €") == "1234.50 EUR"
    assert normalisiere("person", "Anna") is None
    assert normalisiere("iban", "Quark") is None
