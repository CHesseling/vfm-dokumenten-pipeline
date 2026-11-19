import os
import tempfile
import threading
from typing import Protocol

import httpx

from app.modell_sperre import modell_sperre
from app.providers.llm_client import provider_fehler_abbilden


class Transkribierer(Protocol):
    def transkribieren(self, inhalt: bytes, dateiname: str) -> str: ...


def _lade_whisper(modell: str, download_root: str):
    from faster_whisper import WhisperModel

    return WhisperModel(modell, device="cpu", compute_type="int8", download_root=download_root)


_WHISPER: dict[tuple[str, str], object] = {}
_WHISPER_LOCK = threading.Lock()


def _whisper(modell: str, download_root: str):
    with _WHISPER_LOCK:
        if (modell, download_root) not in _WHISPER:
            _WHISPER[(modell, download_root)] = _lade_whisper(modell, download_root)
        return _WHISPER[(modell, download_root)]


class LokalerTranskribierer:
    def __init__(self, model: str, download_root: str):
        self.model = model
        self._download_root = download_root
        self._modell = None

    def transkribieren(self, inhalt: bytes, dateiname: str) -> str:
        suffix = os.path.splitext(dateiname)[1]
        with modell_sperre("Whisper"), tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            if self._modell is None:
                self._modell = _whisper(self.model, self._download_root)
            tmp.write(inhalt)
            tmp.flush()
            segmente, _ = self._modell.transcribe(tmp.name, language="de", beam_size=5, vad_filter=True)
            # segmente ist ein Generator: die Rechnung passiert hier, noch unter der Sperre
            return " ".join(s.text.strip() for s in segmente).strip()


class ApiTranskribierer:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 600.0):
        self.model = model
        self.rolle = "transcribe"
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    def transkribieren(self, inhalt: bytes, dateiname: str) -> str:
        try:
            response = self._client.post(
                "/audio/transcriptions",
                files={"file": (dateiname, inhalt)},
                data={"model": self.model, "language": "de"},
            )
            response.raise_for_status()
        except httpx.HTTPError as fehler:
            abgebildet = provider_fehler_abbilden(
                fehler, self.rolle, self._base_url, self.model, timeout=self._timeout
            )
            if abgebildet is None:
                raise
            raise abgebildet from fehler
        return response.json()["text"]
