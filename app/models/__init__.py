"""SQLModel-Tabellen der Workshop-Pipeline."""

from app.models.auswertung import Analyse, Chunk, Embedding, Entitaet, Lauf
from app.models.dokument import Dokument, TextExtraktion

__all__ = [
    "Analyse", "Chunk", "Dokument", "Embedding", "Entitaet", "Lauf", "TextExtraktion",
]
