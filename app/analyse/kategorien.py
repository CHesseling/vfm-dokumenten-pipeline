"""Kategorien fuer die Klassifikation, aus einer YAML-Datei (Liste aus name + beschreibung)."""

from dataclasses import dataclass

import yaml

from app.config import repo_pfad


@dataclass(frozen=True)
class Kategorie:
    name: str
    beschreibung: str


STANDARD_FRAGE = "Ordne das Dokument genau einer der folgenden Kategorien zu:"


@dataclass(frozen=True)
class Klassifikationsvorgabe:
    """Frage und Kategorien – gleich fuer LLM und CLEF, damit der Vergleich fair ist."""

    frage: str
    kategorien: list[Kategorie]


def lade_klassifikation(pfad: str) -> Klassifikationsvorgabe:
    """Liest `{frage, kategorien}` oder (alte Form) eine reine Liste mit Standardfrage."""
    datei = repo_pfad(pfad)
    if not datei.is_file():
        raise ValueError(f"Kategorien-Datei nicht gefunden: {pfad}")
    try:
        daten = yaml.safe_load(datei.read_text(encoding="utf-8"))
    except yaml.YAMLError as fehler:
        raise ValueError(f"Kategorien-Datei {pfad} ist kein gültiges YAML: {fehler}") from fehler
    frage = STANDARD_FRAGE
    if isinstance(daten, dict):
        frage = str(daten.get("frage") or "").strip()
        if not frage:
            raise ValueError(f"Kategorien-Datei {pfad}: 'frage' fehlt oder ist leer")
        daten = daten.get("kategorien")
    if not isinstance(daten, list) or not daten:
        raise ValueError(f"Kategorien-Datei {pfad}: 'kategorien' ist leer oder keine Liste")
    try:
        kategorien = [Kategorie(str(e["name"]), str(e.get("beschreibung", ""))) for e in daten]
    except (TypeError, KeyError, AttributeError) as fehler:
        raise ValueError(f"Kategorien-Datei {pfad}: jeder Eintrag braucht 'name' und 'beschreibung'") from fehler
    return Klassifikationsvorgabe(frage, kategorien)


def lade_kategorien(pfad: str) -> list[Kategorie]:
    return lade_klassifikation(pfad).kategorien
