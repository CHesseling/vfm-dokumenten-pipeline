"""LLM-NER: das Chat-Modell nennt Entitaeten, Offsets werden per Textsuche ergaenzt."""

import re

from pydantic import BaseModel

from app.ner.labels import LabelWunsch, standard_labels
from app.ner.treffer import Treffer
from app.providers.llm_client import LLMClient

FENSTER_ZEICHEN = 6000

ERKLAERUNG = {
    "person": "Namen von Personen",
    "organisation": "Firmen, Behörden, Vereine, Institutionen",
    "ort": "Städte, Länder, Straßen, geografische Orte",
    "datum": "Datumsangaben",
    "geldbetrag": "Geldbeträge mit Währung",
    "iban": "IBAN-Kontonummern",
    "telefon": "Telefonnummern",
    "email": "E-Mail-Adressen",
}


class LlmEntitaet(BaseModel):
    label: str
    text: str


class LlmEntitaeten(BaseModel):
    entitaeten: list[LlmEntitaet]


def _fenster(text: str) -> list[str]:
    teile = []
    start = 0
    while start < len(text):
        ende = min(start + FENSTER_ZEICHEN, len(text))
        if ende < len(text):
            grenze = max(text.rfind("\n", start, ende), text.rfind(" ", start, ende))
            if grenze > start:
                ende = grenze
        teile.append(text[start:ende])
        start = ende
    return teile


def _nachrichten(teil: str, labels: list[LabelWunsch]) -> list[dict]:
    liste = "\n".join(f"- {l.name}: {ERKLAERUNG.get(l.name) or l.begriff or l.name}" for l in labels)
    return [
        {
            "role": "system",
            "content": (
                "Du extrahierst benannte Entitäten aus deutschen Texten. Erlaubte Labels:\n"
                f"{liste}\n"
                "Gib jede Entität genau so zurück, wie sie im Text steht (wörtlich, nicht umformuliert). "
                "Erfinde nichts. Antworte als JSON mit dem Feld 'entitaeten', einer Liste aus "
                "{'label': ..., 'text': ...}."
            ),
        },
        {"role": "user", "content": teil},
    ]


def _muster(wert: str) -> re.Pattern:
    """Wortgrenzen nur dort, wo die Entitaet mit einem Wortzeichen beginnt/endet."""
    links = r"(?<!\w)" if re.match(r"\w", wert[0]) else ""
    rechts = r"(?!\w)" if re.match(r"\w", wert[-1]) else ""
    return re.compile(links + re.escape(wert) + rechts)


def llm_ner(
    client: LLMClient, text: str, labels: list[LabelWunsch] | None = None, statistik: dict | None = None
) -> list[Treffer]:
    """Treffer mit Offsets (alle Vorkommen). `statistik["verworfen"]` zaehlt
    erfundene (nicht im Text vorkommende) bzw. label-fremde Antworten."""
    labels = list(labels or standard_labels())
    namen = {l.name for l in labels}
    gefragt: set[tuple[str, str]] = set()
    verworfen = 0
    for teil in _fenster(text):
        antwort = client.chat_json(_nachrichten(teil, labels), LlmEntitaeten)
        for e in antwort.entitaeten:
            wert = e.text.strip()
            label = e.label.strip().lower()
            if label not in namen or not wert or wert not in text:
                verworfen += 1
                continue
            gefragt.add((label, wert))
    treffer = [
        Treffer(label, m.group(), m.start(), m.end())
        for label, wert in sorted(gefragt)
        for m in re.finditer(_muster(wert), text)
    ]
    if statistik is not None:
        statistik["verworfen"] = verworfen
    return sorted(treffer, key=lambda t: (t.start, t.ende, t.label))
