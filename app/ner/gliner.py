"""GliNER2-NER mit Fensterung (lokales Modell, laedt erst bei Erstbenutzung).

GliNER2 liefert mit `include_spans=True, include_confidence=True` je Treffer
`{"text", "confidence", "start", "end"}` - Offsets relativ zum uebergebenen
Fenster; sie werden hier auf den Gesamttext umgerechnet. Fehlen Offsets,
wird ersatzweise per `finditer` im Fenster gesucht.
"""

import re
import threading

from app.modell_sperre import modell_sperre
from app.ner.labels import LabelWunsch, ist_bekannt
from app.ner.treffer import Treffer

# internes Label -> Modell-Label (Modell ist englisch trainiert, siehe Spike)
GLINER_LABELS = {
    "person": "person",
    "organisation": "company",
    "ort": "location",
    "datum": "date",
    "geldbetrag": "amount",
}

FENSTER_ZEICHEN = 1200


def modell_labels(labels: list[LabelWunsch] | None) -> dict[str, str]:
    """Modell-Begriff -> internes Label. Begriff aus der Eingabe, sonst GLINER_LABELS;
    bekannte Labels ohne GliNER-Begriff (iban, telefon, email) werden uebersprungen,
    eigene Labels ohne Begriff gehen mit ihrem Namen ans Modell. Bei Kollision gewinnt das erste."""
    if labels is None:
        return {begriff: name for name, begriff in GLINER_LABELS.items()}
    rueck: dict[str, str] = {}
    for l in labels:
        begriff = l.begriff or GLINER_LABELS.get(l.name) or (None if ist_bekannt(l.name) else l.name)
        if begriff is not None:
            rueck.setdefault(begriff, l.name)
    return rueck
UEBERLAPPUNG = 100


def _lade_modell(name: str):
    from gliner2 import GLiNER2

    return GLiNER2.from_pretrained(name)


# Cache mit Lock: parallele GUI-Anfragen sollen das Modell nicht doppelt laden.
_MODELLE: dict[str, object] = {}
_MODELLE_LOCK = threading.Lock()


def _modell_geladen(name: str):
    with _MODELLE_LOCK:
        if name not in _MODELLE:
            _MODELLE[name] = _lade_modell(name)
        return _MODELLE[name]


def _fenster(text: str) -> list[tuple[int, str]]:
    """(Offset, Teiltext)-Paare, Grenzen an Leerraum, mit Ueberlappung."""
    if len(text) <= FENSTER_ZEICHEN:
        return [(0, text)]
    ergebnis = []
    start = 0
    while start < len(text):
        ende = min(start + FENSTER_ZEICHEN, len(text))
        if ende < len(text):
            grenze = max(text.rfind(c, start + UEBERLAPPUNG + 1, ende) for c in (" ", "\n", "\t"))
            if grenze > start:
                ende = grenze
        ergebnis.append((start, text[start:ende]))
        if ende >= len(text):
            break
        neu = max(ende - UEBERLAPPUNG, start + 1)
        # an Wortgrenze: hinter den naechsten Leerraum vorruecken
        m = re.search(r"\s", text[neu:ende])
        start = neu + m.end() if m else ende
    return ergebnis


class GlinerNer:
    def __init__(self, modell: str, schwelle: float = 0.5):
        self.modell = modell
        self.schwelle = schwelle

    def finde(self, text: str, labels: list[LabelWunsch] | None = None) -> list[Treffer]:
        rueck = modell_labels(labels)
        if not rueck or not text.strip():
            return []
        with modell_sperre("GLiNER"):
            modell = _modell_geladen(self.modell)
            fenster = [
                (offset, teil, modell.extract_entities(
                    teil, list(rueck), threshold=self.schwelle, include_spans=True, include_confidence=True
                ))
                for offset, teil in _fenster(text)
            ]
        gesehen: set[tuple[str, int, int]] = set()
        treffer: list[Treffer] = []
        for offset, teil, roh in fenster:
            for modell_label, eintraege in roh.get("entities", {}).items():
                label = rueck.get(modell_label)
                if label is None:
                    continue
                for e in eintraege:
                    if isinstance(e, str):
                        e = {"text": e}
                    if "start" in e and "end" in e:
                        spannen = [(e["start"], e["end"])]
                    else:
                        spannen = [m.span() for m in re.finditer(re.escape(e["text"]), teil)]
                    for s, z in spannen:
                        schluessel = (label, offset + s, offset + z)
                        if schluessel in gesehen:
                            continue
                        gesehen.add(schluessel)
                        treffer.append(
                            Treffer(label, text[offset + s : offset + z], offset + s, offset + z,
                                    None, e.get("confidence"))
                        )
        # Am Fensterrand abgeschnittene Spans: gleiches Label, vollstaendig in
        # einem anderen Treffer enthalten -> den laengeren behalten.
        treffer = [
            t for t in treffer
            if not any(
                o is not t and o.label == t.label and o.start <= t.start and t.ende <= o.ende
                and (o.ende - o.start) > (t.ende - t.start)
                for o in treffer
            )
        ]
        return sorted(treffer, key=lambda t: (t.start, t.ende))
