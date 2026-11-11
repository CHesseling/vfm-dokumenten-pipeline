"""Kategorien fuer die Klassifikation, aus einer YAML-Datei (Liste aus name + beschreibung)."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Kategorie:
    name: str
    beschreibung: str


def lade_kategorien(pfad: str) -> list[Kategorie]:
    datei = Path(pfad)
    if not datei.is_file():
        raise ValueError(f"Kategorien-Datei nicht gefunden: {pfad}")
    try:
        daten = yaml.safe_load(datei.read_text(encoding="utf-8"))
    except yaml.YAMLError as fehler:
        raise ValueError(f"Kategorien-Datei {pfad} ist kein gültiges YAML: {fehler}") from fehler
    if not isinstance(daten, list) or not daten:
        raise ValueError(f"Kategorien-Datei {pfad} ist leer oder keine Liste")
    try:
        return [Kategorie(str(e["name"]), str(e.get("beschreibung", ""))) for e in daten]
    except (TypeError, KeyError, AttributeError) as fehler:
        raise ValueError(f"Kategorien-Datei {pfad}: jeder Eintrag braucht 'name' und 'beschreibung'") from fehler
