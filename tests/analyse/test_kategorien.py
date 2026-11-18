import pytest

from app.analyse.kategorien import STANDARD_FRAGE, Kategorie, lade_kategorien, lade_klassifikation


def test_kategorien_laden(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("- name: A\n  beschreibung: erste\n- name: B\n  beschreibung: zweite\n", encoding="utf-8")
    assert lade_kategorien(str(p)) == [Kategorie("A", "erste"), Kategorie("B", "zweite")]


def test_mitgelieferte_datei():
    namen = [k.name for k in lade_kategorien("config/kategorien.yaml")]
    assert namen == ["Juristisches Schreiben", "Vertrag", "Rechnung", "Korrespondenz", "Protokoll", "Privat", "Sonstiges"]


def test_kategorien_fehlen(tmp_path):
    pfad = str(tmp_path / "gibtsnicht.yaml")
    with pytest.raises(ValueError, match="gibtsnicht.yaml"):
        lade_kategorien(pfad)


def test_kategorien_leer(tmp_path):
    p = tmp_path / "leer.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="leer.yaml"):
        lade_kategorien(str(p))


def test_klassifikation_mit_frage(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("frage: Welche Art Dokument ist das?\nkategorien:\n  - name: A\n    beschreibung: erste\n",
                 encoding="utf-8")
    vorgabe = lade_klassifikation(str(p))
    assert vorgabe.frage == "Welche Art Dokument ist das?"
    assert vorgabe.kategorien == [Kategorie("A", "erste")]
    assert lade_kategorien(str(p)) == [Kategorie("A", "erste")]


def test_reine_liste_bekommt_standardfrage(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("- name: A\n  beschreibung: erste\n", encoding="utf-8")
    assert lade_klassifikation(str(p)).frage == STANDARD_FRAGE


@pytest.mark.parametrize("inhalt", ["frage: x\n", "frage: x\nkategorien: []\n", "frage: ''\nkategorien:\n  - name: A\n"])
def test_klassifikation_ungueltig(tmp_path, inhalt):
    p = tmp_path / "k.yaml"
    p.write_text(inhalt, encoding="utf-8")
    with pytest.raises(ValueError):
        lade_klassifikation(str(p))


def test_mitgelieferte_datei_hat_frage():
    assert lade_klassifikation("config/kategorien.yaml").frage.strip()
