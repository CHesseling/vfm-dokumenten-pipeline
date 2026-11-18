"""Verbindungs- und Modellpruefung je Rolle (Grundlage fuer `vfm check`)."""

import base64
import io
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image
from tenacity import RetryError

from app.config import Settings
from app.providers import factory
from app.providers.llm_client import ProviderFehler, bild_nachricht


# Der Check darf nie minutenlang haengen (Chat-Standardbudget sind 600 s):
# kurzes Gesamtbudget je Rolle, Verbindungsaufbau nach wenigen Sekunden aufgeben.
CHECK_GESAMT_TIMEOUT = 90.0
CHECK_VERBINDUNG_TIMEOUT = 5.0


@dataclass
class RollenCheck:
    rolle: str
    backend: str
    modell: str
    ok: bool
    detail: str


def _weisses_png() -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(puffer, format="PNG")
    return puffer.getvalue()


def _fehlertext(fehler: BaseException) -> str:
    if isinstance(fehler, RetryError):  # tenacity ohne reraise (ApiReranker)
        return _fehlertext(fehler.last_attempt.exception())
    if isinstance(fehler, ProviderFehler):
        return fehler.meldung
    if isinstance(fehler, httpx.ConnectError):
        return "nicht erreichbar"
    if isinstance(fehler, httpx.TimeoutException):
        return "Zeitüberschreitung"
    if isinstance(fehler, httpx.HTTPStatusError):
        return f"HTTP {fehler.response.status_code}"
    return str(fehler) or type(fehler).__name__


def _chat(s: Settings) -> str:
    antwort = factory.chat_client(s, gesamt_timeout=CHECK_GESAMT_TIMEOUT, connect_timeout=CHECK_VERBINDUNG_TIMEOUT).chat_text(
        [{"role": "user", "content": "Antworte nur mit OK."}]
    )
    return f"Antwort: {antwort[:40]}"


def _vision(s: Settings) -> str:
    nachricht = bild_nachricht("Welche Farbe?", [(_weisses_png(), "image/png")])
    antwort = factory.vision_client(s, gesamt_timeout=CHECK_GESAMT_TIMEOUT, connect_timeout=CHECK_VERBINDUNG_TIMEOUT).chat_text([nachricht])
    return f"Antwort: {antwort[:40]}"


def _embed(s: Settings) -> str:
    return f"Dimension {len(factory.embedding_client(s, timeout=CHECK_GESAMT_TIMEOUT, connect_timeout=CHECK_VERBINDUNG_TIMEOUT).embed('Test'))}"


def _rerank(s: Settings) -> str:
    if s.rerank_backend == "none":
        return "deaktiviert"
    factory.reranker(s, timeout=CHECK_GESAMT_TIMEOUT, connect_timeout=CHECK_VERBINDUNG_TIMEOUT).rerank("Test", ["erster Text", "zweiter Text"])
    return "Rerank-Aufruf erfolgreich"


def _transcribe(s: Settings) -> str:
    if s.transcribe_backend == "local":
        pfad = Path(s.whisper_pfad)
        if not pfad.is_dir() or not any(pfad.iterdir()):
            raise FileNotFoundError(f"Whisper-Modellordner fehlt oder ist leer: {pfad}")
        return f"Modellordner vorhanden: {pfad}"
    if not s.transcribe_base_url:
        raise ValueError("TRANSCRIBE_BASE_URL fehlt für TRANSCRIBE_BACKEND=api")
    headers = {}
    if key := s.api_key_fuer("transcribe"):
        headers["Authorization"] = f"Bearer {key}"
    httpx.get(
        s.transcribe_base_url.rstrip("/") + "/models", headers=headers, timeout=15.0
    ).raise_for_status()
    return "API erreichbar"


def _classify(s: Settings) -> str:
    if not s.clef_aktiv():
        return "aus – kein CORTECS_API_KEY (CLEF ist optional)"
    httpx.get(
        s.classify_base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {s.api_key_fuer('classify')}"}, timeout=15.0,
    ).raise_for_status()
    return "API erreichbar"


def pruefe_rollen(s: Settings) -> list[RollenCheck]:
    _, vision_modell, _ = s.vision_effektiv()
    rerank_backend = s.rerank_backend
    plan = [
        ("chat", "api", s.chat_model, _chat),
        ("vision", "api", vision_modell, _vision),
        ("embed", "api", s.embed_model, _embed),
        ("rerank", rerank_backend, s.rerank_model if rerank_backend != "none" else "-", _rerank),
        ("transcribe", s.transcribe_backend, s.transcribe_model, _transcribe),
        ("classify", "api", s.classify_model if s.clef_aktiv() else "-", _classify),
    ]
    ergebnisse = []
    for rolle, backend, modell, pruefung in plan:
        try:
            ok, detail = True, pruefung(s)
        except Exception as fehler:  # jede Rolle einzeln, nie ein Traceback
            ok, detail = False, _fehlertext(fehler)
        ergebnisse.append(RollenCheck(rolle, backend, modell, ok, detail))
    return ergebnisse
