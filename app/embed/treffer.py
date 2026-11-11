from dataclasses import dataclass


@dataclass
class SuchTreffer:
    chunk_id: int
    dokument_id: int
    dateiname: str
    text: str
    vektor_rang: int | None
    vektor_score: float | None
    rerank_rang: int | None
    rerank_score: float | None
    snippet: str | None = None
