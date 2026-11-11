import pytest

from app.analyse.kategorien import Kategorie, lade_kategorien


def test_kategorien_laden(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("- name: A\n  beschreibung: erste\n- name: B\n  beschreibung: zweite\n", encoding="utf-8")
    assert lade_kategorien(str(p)) == [Kategorie("A", "erste"), Kategorie("B", "zweite")]


def test_mitgelieferte_datei():
    namen = [k.name for k in lade_kategorien("config/kategorien.yaml")]
    assert namen == ["Vertrag", "Rechnung", "Korrespondenz", "Protokoll", "Privat", "Sonstiges"]


def test_kategorien_fehlen(tmp_path):
    pfad = str(tmp_path / "gibtsnicht.yaml")
    with pytest.raises(ValueError, match="gibtsnicht.yaml"):
        lade_kategorien(pfad)


def test_kategorien_leer(tmp_path):
    p = tmp_path / "leer.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="leer.yaml"):
        lade_kategorien(str(p))
