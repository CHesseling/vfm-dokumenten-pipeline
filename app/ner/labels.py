"""Frei waehlbare NER-Labels und GliNER-Schwelle (Eingabe aus GUI und CLI).

Eingabe: kommagetrennt, je Eintrag `name` oder `name=englischer Begriff`, z. B.
"person, aktenzeichen=file number, behörde". Der Begriff hilft GliNER (englisch
trainiert) und dient dem LLM als Beschreibung.
"""

import re
from dataclasses import dataclass

from app.ner.treffer import LABELS

MAX_LABELS = 20
MAX_NAME = 40
MAX_BEGRIFF = 60
SCHWELLE_MIN = 0.05
SCHWELLE_MAX = 0.95

_NAME = re.compile(r"[a-zäöüß0-9_ -]+")
_BEGRIFF = re.compile(r"[\w .,'-]+")


@dataclass(frozen=True)
class LabelWunsch:
    name: str
    begriff: str | None = None


def ist_bekannt(name: str) -> bool:
    return name in LABELS


def standard_labels() -> list[LabelWunsch]:
    return [LabelWunsch(l) for l in LABELS]


def labels_parsen(eingabe: str | None) -> list[LabelWunsch] | None:
    """None bei leerer Eingabe (= Standard-Labels); ValueError bei ungueltiger Eingabe."""
    ergebnis: list[LabelWunsch] = []
    gesehen: set[str] = set()
    for eintrag in (eingabe or "").split(","):
        eintrag = eintrag.strip()
        if not eintrag:
            continue
        name, _, begriff = eintrag.partition("=")
        name, begriff = name.strip().lower(), begriff.strip()
        if not name or len(name) > MAX_NAME or not _NAME.fullmatch(name):
            raise ValueError(
                f"Ungültiges Label „{eintrag[:MAX_NAME]}“ – erlaubt sind Buchstaben, Ziffern, Leerzeichen, _ und -"
                f" (höchstens {MAX_NAME} Zeichen)."
            )
        if begriff and (len(begriff) > MAX_BEGRIFF or not _BEGRIFF.fullmatch(begriff)):
            raise ValueError(f"Ungültiger Begriff bei „{name}“ – höchstens {MAX_BEGRIFF} Zeichen, kein weiteres „=“.")
        if name in gesehen:
            continue
        gesehen.add(name)
        ergebnis.append(LabelWunsch(name, begriff or None))
    if len(ergebnis) > MAX_LABELS:
        raise ValueError(f"Höchstens {MAX_LABELS} Labels.")
    return ergebnis or None


def labels_als_text(labels: list[LabelWunsch] | None) -> str:
    return ", ".join(f"{l.name}={l.begriff}" if l.begriff else l.name for l in (labels or standard_labels()))


def schwelle_pruefen(wert: float) -> float:
    if not SCHWELLE_MIN <= wert <= SCHWELLE_MAX:
        raise ValueError(f"Die Schwelle muss zwischen {SCHWELLE_MIN} und {SCHWELLE_MAX} liegen.")
    return wert
