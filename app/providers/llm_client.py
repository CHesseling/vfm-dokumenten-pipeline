import base64
import json
import logging
import re
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.providers.url import ohne_zugangsdaten

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMExtractionError(Exception):
    pass


class ProviderFehler(Exception):
    """Lesbarer Fehler beim Zugriff auf einen Modell-Anbieter (Chat, Vision, Embedding, ...)."""

    def __init__(self, rolle: str, base_url: str, modell: str, meldung: str):
        self.rolle = rolle
        self.base_url = ohne_zugangsdaten(base_url) or base_url
        self.modell = modell
        self.meldung = meldung
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.rolle}: {self.meldung} ({self.modell} @ {self.base_url})"


def provider_fehler_abbilden(
    fehler: BaseException, rolle: str, base_url: str, modell: str, timeout: float | None = None
) -> ProviderFehler | None:
    """Ordnet bekannte httpx-Fehler einer lesbaren Meldung zu (sonst None).

    timeout: das wirksame Zeitbudget in Sekunden (nur fuer die Meldung)."""
    meldung = None
    if isinstance(fehler, httpx.ConnectError):
        meldung = "nicht erreichbar"
    elif isinstance(fehler, (httpx.TimeoutException, LLMGesamtTimeoutError)):
        meldung = "Zeitüberschreitung" if timeout is None else f"Zeitüberschreitung nach {timeout:g} s"
    elif isinstance(fehler, httpx.HTTPStatusError):
        status = fehler.response.status_code
        if status == 404:
            meldung = "Modell nicht gefunden"
        elif status in (401, 403):
            meldung = "API-Key fehlt oder ist ungültig"
        elif status >= 500:
            meldung = f"Serverfehler {status}: {fehler.response.text[:200]}"
    return ProviderFehler(rolle, base_url, modell, meldung) if meldung else None


def bild_nachricht(text: str, bilder: list[tuple[bytes, str]]) -> dict:
    """User-Message mit Text und Bildern; je Bild (Inhalt, MIME-Typ)."""
    content: list[dict] = [{"type": "text", "text": text}]
    for inhalt, mime in bilder:
        b64 = base64.b64encode(inhalt).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return {"role": "user", "content": content}


# Marker: Anfrage ganz ohne response_format (Freitext)
_FREITEXT: dict = {}
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMGesamtTimeoutError(httpx.HTTPError):
    """Der Gesamt-Zeitbudget fuer einen Chat-Completion-Call wurde ueberschritten.

    Erbt von httpx.HTTPError (fachlich ein Transportproblem), wird aber
    bewusst NICHT wiederholt - siehe _wiederholbar.

    httpx' eigener 'read'-Timeout misst nur die Luecke ZWISCHEN empfangenen
    Bytes, nicht die Gesamtdauer einer Anfrage - manche LLM-Gateways (z. B.
    OpenRouter) halten die Verbindung waehrend langer Generierungen durch
    gelegentliche Keep-Alive-Bytes am Leben, wodurch httpx' Timeout nie
    ausloest, selbst wenn eine einzelne Antwort viele Minuten braucht.
    Dieser Wrapper erzwingt ein echtes Gesamt-Zeitbudget."""


# Puffer zwischen gesamt_timeout und httpx' eigenem Timeout, siehe LLMClient.__init__.
HTTPX_TIMEOUT_PUFFER_SEKUNDEN = 30.0


def _wiederholbar(fehler: BaseException) -> bool:
    """Netzwerk-/Serverfehler (5xx) sind oft voruebergehend und werden wiederholt.
    Eine Zeitueberschreitung nicht: bei temperature=0 braucht dieselbe Anfrage
    beim naechsten Versuch genauso lange - auf dem Server kosteten drei
    identische Versuche 9 Minuten pro Wochenplan-Tag, ohne Aussicht auf Erfolg."""
    if isinstance(fehler, (LLMGesamtTimeoutError, httpx.ReadTimeout)):
        return False
    if isinstance(fehler, httpx.HTTPStatusError):
        # 4xx: der Server lehnt die Anfrage selbst ab - identisch wiederholt
        # gibt es dieselbe Antwort. Ausnahmen: Timeout (408), Rate-Limit (429).
        status = fehler.response.status_code
        return not (400 <= status < 500) or status in (408, 429)
    return isinstance(fehler, httpx.HTTPError)


_UHRZEIT_MUSTER = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


def _llm_schema(schema):
    """JSON-Schema fuer Structured Outputs: Pydantic beschreibt `time` als
    {"format": "time"} - laut JSON Schema (RFC 3339 full-time) MIT Zeitzone.
    Eine Grammatik, die das erzwingt, zwingt das Modell zu erfundenen Offsets
    ("09:30:00-09:30", im A/B-Test beobachtet). Deshalb ein HH:MM-Muster."""
    if isinstance(schema, dict):
        if schema.get("format") == "time":
            return {k: v for k, v in schema.items() if k != "format"} | {"pattern": _UHRZEIT_MUSTER}
        return {k: _llm_schema(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_llm_schema(v) for v in schema]
    return schema


class DoppelterSchluesselError(ValueError):
    pass


def _ohne_doppelte_schluessel(paare: list[tuple[str, object]]) -> dict:
    """json.loads behaelt bei doppelten Schluesseln still nur den letzten Wert.
    Im JSON-Modus schrieb ein Modell '{"verfahren": [A], "verfahren": [B], ...}'
    - 14 von 15 Verfahren gingen verloren, ohne dass die Antwort als fehlerhaft
    auffiel. Jetzt ein Fehler, der die Korrektur-Runde in chat_json ausloest."""
    ergebnis: dict = {}
    for schluessel, wert in paare:
        if schluessel in ergebnis:
            raise DoppelterSchluesselError(
                f"Schluessel {schluessel!r} kommt doppelt vor - alle Eintraege gehoeren in EIN Array/Objekt"
            )
        ergebnis[schluessel] = wert
    return ergebnis


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        gesamt_timeout: float = 600.0,
        structured_outputs: bool = False,
        extra_body: dict | None = None,
        rolle: str = "chat",
        connect_timeout: float | None = None,
    ):
        self.model = model
        self.rolle = rolle
        self._base_url = base_url.rstrip("/")
        self._extra_body = dict(extra_body or {})
        self._gesamt_timeout = gesamt_timeout
        # True: response_format "json_schema" - der Server erzwingt das Schema
        # beim Generieren (vLLM: Guided Decoding). Verhindert Strukturfehler wie
        # doppelte Schluessel oder verschachtelte Arrays; False: JSON-Modus, das
        # Schema steht nur im Prompt.
        self._structured_outputs = structured_outputs
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            # httpx' eigener Timeout muss spaeter feuern als gesamt_timeout
            # (Puffer statt Gleichstand): sonst gewinnt bei nicht gestreamten
            # Antworten mal httpx' ReadTimeout das Rennen, mal das wall-clock-
            # Budget aus _chat_completion - auf dem Server lagen beide nur 46 ms
            # auseinander. Siehe LLMGesamtTimeoutError-Docstring.
            timeout=httpx.Timeout(
                max(timeout, gesamt_timeout + HTTPX_TIMEOUT_PUFFER_SEKUNDEN), connect=connect_timeout
            ),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_wiederholbar),
        reraise=True,
    )
    def _chat_completion(self, messages: list[dict], response_format: dict | None = None) -> str:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._chat_completion_request, messages, response_format)
        try:
            return future.result(timeout=self._gesamt_timeout)
        except FutureTimeoutError as fehler:
            logger.warning(
                "LLM-Call ueberschritt Gesamt-Zeitbudget von %.0fs (Modell=%s)",
                self._gesamt_timeout,
                self.model,
            )
            raise LLMGesamtTimeoutError(
                f"Chat-Completion-Aufruf ueberschritt das Gesamt-Zeitbudget von "
                f"{self._gesamt_timeout}s (Modell: {self.model})"
            ) from fehler
        finally:
            # Nicht auf den Thread warten (ein "with" taete das): nach einer
            # Zeitueberschreitung endet die Anfrage erst durch httpx' eigenes,
            # spaeteres Timeout - der Aufrufer soll sofort weitermachen koennen.
            pool.shutdown(wait=False)

    def _chat_completion_request(self, messages: list[dict], response_format: dict | None = None) -> str:
        start = time.monotonic()
        logger.info("LLM-Anfrage gestartet (Modell=%s, Nachrichten=%d)", self.model, len(messages))
        try:
            body = {**self._extra_body, "model": self.model, "messages": messages, "temperature": 0}
            if response_format is not _FREITEXT:
                body["response_format"] = response_format or {"type": "json_object"}
            response = self._client.post("/chat/completions", json=body)
            response.raise_for_status()
        except httpx.HTTPError:
            logger.warning(
                "LLM-Anfrage fehlgeschlagen nach %.1fs (Modell=%s)", time.monotonic() - start, self.model
            )
            raise
        dauer = time.monotonic() - start
        inhalt = response.json()["choices"][0]["message"]["content"]
        logger.info(
            "LLM-Antwort erhalten nach %.1fs (Modell=%s, content_len=%s)",
            dauer,
            self.model,
            len(inhalt) if inhalt else 0,
        )
        return inhalt

    def _response_format(self, schema: type[BaseModel]) -> dict:
        if not self._structured_outputs:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": _llm_schema(schema.model_json_schema()), "strict": True},
        }

    def _chat_completion_mit_format(self, messages: list[dict], schema: type[BaseModel]) -> tuple[str, dict]:
        response_format = self._response_format(schema)
        try:
            return self._chat_completion(messages, response_format), response_format
        except httpx.HTTPStatusError as fehler:
            if response_format["type"] != "json_schema" or fehler.response.status_code != 400:
                raise
            # Der Server unterstuetzt das Schema (oder ein Detail davon) nicht -
            # sonst scheitert JEDE Anfrage. Dauerhaft auf den JSON-Modus wechseln.
            logger.warning(
                "Structured Outputs vom Server abgelehnt (%s) - wechsle dauerhaft auf JSON-Modus",
                fehler.response.text[:200],
            )
            self._structured_outputs = False
            response_format = self._response_format(schema)
            return self._chat_completion(messages, response_format), response_format

    @contextmanager
    def _providerfehler(self):
        try:
            yield
        except httpx.HTTPError as fehler:
            abgebildet = provider_fehler_abbilden(
                fehler, self.rolle, self._base_url, self.model, timeout=self._gesamt_timeout
            )
            if abgebildet is None:
                raise
            raise abgebildet from fehler

    def chat_text(self, messages: list[dict]) -> str:
        """Freitext-Antwort ohne response_format; <think>-Bloecke werden entfernt."""
        with self._providerfehler():
            roh = self._chat_completion(messages, _FREITEXT)
        return _THINK_BLOCK.sub("", roh or "").strip()

    def chat_json(self, messages: list[dict], schema: type[T]) -> T:
        with self._providerfehler():
            return self._chat_json(messages, schema)

    def _chat_json(self, messages: list[dict], schema: type[T]) -> T:
        roh, response_format = self._chat_completion_mit_format(messages, schema)
        ergebnis, erster_fehler = self._parsen_und_validieren(roh, schema)
        if ergebnis is not None:
            return ergebnis

        korrektur_messages = messages + [
            {"role": "assistant", "content": roh or ""},
            {
                "role": "user",
                "content": (
                    "Die vorherige Antwort war kein gueltiges JSON fuer das erwartete Schema "
                    f"(Fehler: {erster_fehler}). Falls die Antwort leer war, wurde vermutlich das "
                    "Token-Limit waehrend interner Ueberlegungen ausgeschoepft - antworte diesmal "
                    "direkt und ausschliesslich mit dem JSON-Objekt, ohne Erlaeuterungen davor. "
                    "Bitte gib ausschliesslich valides JSON zurueck, das exakt dem beschriebenen Schema entspricht."
                ),
            },
        ]
        roh_retry = self._chat_completion(korrektur_messages, response_format)
        ergebnis, zweiter_fehler = self._parsen_und_validieren(roh_retry, schema)
        if ergebnis is not None:
            return ergebnis
        raise LLMExtractionError(
            f"LLM-Antwort konnte nicht als {schema.__name__} validiert werden: {zweiter_fehler}"
        ) from zweiter_fehler

    @staticmethod
    def _parsen_und_validieren(roh: str | None, schema: type[T]) -> tuple[T | None, Exception | None]:
        if roh is None:
            return None, ValueError("Antwort enthielt keinen Inhalt (content=null)")
        try:
            daten = json.loads(roh, object_pairs_hook=_ohne_doppelte_schluessel)
            return schema.model_validate(daten), None
        except (json.JSONDecodeError, ValidationError, DoppelterSchluesselError) as fehler:
            return None, fehler

    def chat_json_with_image(
        self, system_prompt: str, user_text: str, bilder: list[tuple[bytes, str]], schema: type[T]
    ) -> T:
        messages = [
            {"role": "system", "content": system_prompt},
            bild_nachricht(user_text, bilder),
        ]
        return self.chat_json(messages, schema)
