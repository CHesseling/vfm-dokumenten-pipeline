import html
import re

from fastapi import APIRouter, Depends, Request
from markupsafe import Markup
from pydantic import BaseModel
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.embed.rag import antwort_erzeugen
from app.embed.suche import KeineEmbeddingsFehler, semantische_suche, volltext_suche
from app.providers.factory import chat_client, embedding_client, reranker
from app.providers.llm_client import ProviderFehler
from app.providers.rerank import KeinReranker
from app.web.vorlagen import templates

router = APIRouter()


def _snippet_html(snippet: str) -> Markup:
    """Snippet escapen, nur die <b>-Markierung der Suche wieder zulassen."""
    return Markup(html.escape(snippet).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>"))


def antwort_html(text: str, dokument_ids: list[int]) -> str:
    """LLM-Text zuerst escapen, dann [n] in Links auf die Quelle verwandeln."""
    def ersetze(m: re.Match) -> str:
        n = int(m.group(1))
        if 1 <= n <= len(dokument_ids):
            return f'<a href="/dokumente/{dokument_ids[n - 1]}">[{n}]</a>'
        return m.group(0)

    return re.sub(r"\[(\d+)\]", ersetze, html.escape(text)).replace("\n", "<br>")


@router.get("/suche")
def suche_seite(
    request: Request,
    q: str = "",
    modus: str = "volltext",
    rerank: str = "",
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    modus = modus if modus in ("volltext", "semantisch") else "volltext"
    treffer, hinweis, mit_rerank = [], None, False
    if q.strip():
        try:
            if modus == "volltext":
                treffer = volltext_suche(session, q, limit=s.rag_top_k * 2)
            else:
                rr = reranker(s) if rerank == "1" else KeinReranker()
                mit_rerank = not isinstance(rr, KeinReranker)
                treffer = semantische_suche(session, q, embedding_client(s), rr, s.rag_top_n, s.rag_top_k)
        except (KeineEmbeddingsFehler, ProviderFehler, ValueError) as fehler:
            hinweis = str(fehler)
    return templates.TemplateResponse(
        request,
        "suche.html",
        {
            "q": q, "modus": modus, "rerank": rerank == "1", "treffer": treffer, "hinweis": hinweis,
            "mit_rerank": mit_rerank, "snippet_html": _snippet_html,
        },
    )


class AntwortAnfrage(BaseModel):
    frage: str
    modus: str = "semantisch"


@router.post("/suche/antwort")
def suche_antwort(
    daten: AntwortAnfrage,
    session: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
):
    try:
        treffer = semantische_suche(
            session, daten.frage, embedding_client(s), reranker(s), s.rag_top_n, s.rag_top_k
        )
        antwort = antwort_erzeugen(chat_client(s), daten.frage, treffer)
    except (KeineEmbeddingsFehler, ProviderFehler, ValueError) as fehler:
        return {"fehler": str(fehler)}
    return {
        "text_html": antwort_html(antwort.text, [t.dokument_id for t in antwort.quellen]),
        "quellen": [
            {"nummer": n, "dokument_id": t.dokument_id, "dateiname": t.dateiname}
            for n, t in enumerate(antwort.quellen, 1)
        ],
    }
