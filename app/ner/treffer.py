from dataclasses import dataclass

# Entitaets-Labels, projektweit (Muster, GliNER und LLM nutzen dieselben)
LABELS = ("person", "organisation", "ort", "datum", "geldbetrag", "iban", "telefon", "email")


@dataclass(frozen=True)
class Treffer:
    label: str
    text: str
    start: int
    ende: int
    normalisiert: str | None = None
    score: float | None = None
