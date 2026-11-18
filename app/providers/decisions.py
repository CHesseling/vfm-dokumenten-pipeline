"""Classifier ueber die Decisions-API (Cortecs, Modell CLEF): Wahrscheinlichkeit je Kategorie.

Format "Decisions": eine choice-Frage, Antwort mit `choice`, `confidence` und
`probabilities` (Liste aus value/probability). Siehe docs.cortecs.ai/api/decisions.
"""

from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.analyse.kategorien import Kategorie
from app.providers.llm_client import _wiederholbar, provider_fehler_abbilden


@dataclass(frozen=True)
class ClefAntwort:
    kategorie: str
    sicherheit: float
    wahrscheinlichkeiten: dict[str, float]


class DecisionsClient:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 60.0,
                 rolle: str = "classify"):
        self.model = model
        self.rolle = rolle
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_wiederholbar),
        reraise=True,
    )
    def _anfrage(self, body: dict) -> dict:
        response = self._client.post("/decisions", json=body)
        response.raise_for_status()
        return response.json()

    def klassifiziere(self, text: str, frage: str, kategorien: list[Kategorie]) -> ClefAntwort:
        body = {
            "model": self.model,
            "input": text,
            "questions": [{
                "type": "choice",
                "name": "kategorie",
                "instructions": frage,
                "choices": [{"value": k.name, "description": k.beschreibung} for k in kategorien],
            }],
        }
        try:
            daten = self._anfrage(body)
        except httpx.HTTPError as fehler:
            abgebildet = provider_fehler_abbilden(fehler, self.rolle, self._base_url, self.model, timeout=self._timeout)
            if abgebildet is None:
                raise
            raise abgebildet from fehler
        antwort = (daten.get("answers") or [{}])[0]
        if antwort.get("type") != "choice" or "choice" not in antwort:
            raise ValueError(f"CLEF hat die Antwort verweigert oder nichts gewählt (Typ: {antwort.get('type')})")
        return ClefAntwort(
            kategorie=str(antwort["choice"]),
            sicherheit=float(antwort.get("confidence", 0.0)),
            wahrscheinlichkeiten={str(p["value"]): float(p["probability"]) for p in antwort.get("probabilities", [])},
        )
