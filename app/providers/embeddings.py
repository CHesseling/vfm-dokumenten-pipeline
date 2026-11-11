import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.providers.llm_client import ProviderFehler, _wiederholbar, provider_fehler_abbilden


class EmbeddingClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        batch: int = 32,
        rolle: str = "embed",
    ):
        self.model = model
        self.rolle = rolle
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self._batch = max(1, batch)
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
    def _anfrage(self, eingabe: str | list[str]) -> list[dict]:
        response = self._client.post("/embeddings", json={"model": self.model, "input": eingabe})
        response.raise_for_status()
        return response.json()["data"]

    def _anfrage_lesbar(self, eingabe: str | list[str]) -> list[dict]:
        try:
            return self._anfrage(eingabe)
        except httpx.HTTPError as fehler:
            abgebildet = provider_fehler_abbilden(
                fehler, self.rolle, self._base_url, self.model, timeout=self._timeout
            )
            if abgebildet is None:
                raise
            raise abgebildet from fehler

    @property
    def batch(self) -> int:
        return self._batch

    def embed(self, text: str) -> list[float]:
        return self._anfrage_lesbar(text)[0]["embedding"]

    def embed_viele(self, texte: list[str]) -> list[list[float]]:
        ergebnis: list[list[float]] = []
        for start in range(0, len(texte), self._batch):
            daten = self._anfrage_lesbar(texte[start : start + self._batch])
            ergebnis.extend(d["embedding"] for d in sorted(daten, key=lambda d: d["index"]))
        return ergebnis


__all__ = ["EmbeddingClient", "ProviderFehler"]
