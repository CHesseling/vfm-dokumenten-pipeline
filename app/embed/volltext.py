"""Volltextsuche ueber Chunks aktiver Extraktionen (PostgreSQL, deutsche Stammformen)."""

from sqlalchemy import text
from sqlmodel import Session

from app.embed.treffer import SuchTreffer

_SQL = text(
    """
    SELECT c.id, d.id, d.dateiname, c.text,
           ts_headline('german', c.text, q.query,
                       'StartSel=<b>, StopSel=</b>, MaxWords=35, MinWords=15') AS snippet
    FROM chunk c
    JOIN textextraktion t ON t.id = c.textextraktion_id AND t.ist_aktiv
    JOIN dokument d ON d.id = t.dokument_id,
         websearch_to_tsquery('german', :q) AS q(query)
    WHERE c.tsv @@ q.query
    ORDER BY ts_rank(c.tsv, q.query) DESC, c.id
    LIMIT :limit
    """
)


def volltext_suche(session: Session, anfrage: str, limit: int = 20) -> list[SuchTreffer]:
    if not anfrage.strip():
        return []
    zeilen = session.execute(_SQL, {"q": anfrage, "limit": limit}).all()
    return [
        SuchTreffer(
            chunk_id=z[0], dokument_id=z[1], dateiname=z[2], text=z[3],
            vektor_rang=None, vektor_score=None, rerank_rang=None, rerank_score=None, snippet=z[4],
        )
        for z in zeilen
    ]
