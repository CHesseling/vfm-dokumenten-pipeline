import threading
from typing import Protocol

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.providers.llm_client import _wiederholbar, provider_fehler_abbilden


class Reranker(Protocol):
    def rerank(self, frage: str, texte: list[str]) -> list[tuple[int, float]]:
        """(index, score) je Text, absteigend nach Score."""
        ...


class KeinReranker:
    def rerank(self, frage: str, texte: list[str]) -> list[tuple[int, float]]:
        return [(i, 0.0) for i in range(len(texte))]


def _lade_cross_encoder(modell: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(modell)


# Modell-Cache je Name: das Laden dauert (und frisst RAM), GUI-Anfragen laufen in
# parallelen Threads - ohne Lock wuerden zwei Anfragen das Modell doppelt laden.
_ENCODER: dict[str, object] = {}
_ENCODER_LOCK = threading.Lock()


def _cross_encoder(modell: str):
    with _ENCODER_LOCK:
        if modell not in _ENCODER:
            _ENCODER[modell] = _lade_cross_encoder(modell)
        return _ENCODER[modell]


class LokalerReranker:
    def __init__(self, model: str):
        self.model = model
        self._encoder = None

    def rerank(self, frage: str, texte: list[str]) -> list[tuple[int, float]]:
        if not texte:
            return []
        if self._encoder is None:
            self._encoder = _cross_encoder(self.model)
        scores = self._encoder.predict([(frage, t) for t in texte])
        paare = [(i, float(s)) for i, s in enumerate(scores)]
        return sorted(paare, key=lambda p: p[1], reverse=True)


class ApiReranker:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 30.0):
        self.model = model
        self.rolle = "rerank"
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_wiederholbar),
        reraise=True,
    )
    def _anfrage(self, frage: str, texte: list[str]) -> list[dict]:
        response = self._client.post(
            "/rerank", json={"model": self.model, "query": frage, "documents": texte}
        )
        response.raise_for_status()
        return response.json()["results"]

    def rerank(self, frage: str, texte: list[str]) -> list[tuple[int, float]]:
        """Nimmt eine TEI/Cohere-artige Response-Form an
        ({"results": [{"index", "relevance_score"}, ...]})."""
        try:
            ergebnisse = self._anfrage(frage, texte)
        except httpx.HTTPError as fehler:
            abgebildet = provider_fehler_abbilden(
                fehler, self.rolle, self._base_url, self.model, timeout=self._timeout
            )
            if abgebildet is None:
                raise
            raise abgebildet from fehler
        sortiert = sorted(ergebnisse, key=lambda r: r["relevance_score"], reverse=True)
        return [(r["index"], r["relevance_score"]) for r in sortiert]
