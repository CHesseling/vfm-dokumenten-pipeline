import httpx
import respx

from app.providers.transcribe import ApiTranskribierer, LokalerTranskribierer


@respx.mock
def test_api_transkribierer_sendet_multipart():
    route = respx.post("http://stt.example/v1/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "Hallo Welt"})
    )
    t = ApiTranskribierer("http://stt.example/v1", "whisper-1", "key")

    assert t.transkribieren(b"audio", "a.mp3") == "Hallo Welt"
    request = route.calls[0].request
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="language"' in request.content and b"de" in request.content
    assert b'name="model"' in request.content and b"whisper-1" in request.content
    assert request.headers["authorization"] == "Bearer key"


def test_lokaler_transkribierer_verbindet_segmente(monkeypatch):
    monkeypatch.setattr("app.providers.transcribe._WHISPER", {})
    geladen = []

    class Segment:
        def __init__(self, text):
            self.text = text

    class FakeModell:
        def transcribe(self, pfad, **kwargs):
            assert pfad.endswith(".wav")
            assert kwargs == {"language": "de", "beam_size": 5, "vad_filter": True}
            return iter([Segment("Hallo"), Segment("Welt")]), None

    def lader(modell, download_root):
        geladen.append((modell, download_root))
        return FakeModell()

    monkeypatch.setattr("app.providers.transcribe._lade_whisper", lader)
    t = LokalerTranskribierer("small", "/models/whisper")
    assert geladen == []

    assert t.transkribieren(b"x", "aufnahme.wav") == "Hallo Welt"
    assert geladen == [("small", "/models/whisper")]


@respx.mock
def test_api_transkribierer_fehler_wird_providerfehler():
    import pytest

    from app.providers.llm_client import ProviderFehler

    respx.post("http://stt.example/v1/audio/transcriptions").mock(return_value=httpx.Response(503, text="busy"))
    t = ApiTranskribierer("http://stt.example/v1", "whisper-1")
    with pytest.raises(ProviderFehler) as e:
        t.transkribieren(b"audio", "a.mp3")
    assert e.value.rolle == "transcribe" and "Serverfehler 503: busy" in e.value.meldung


def test_whisper_modell_wird_geteilt(monkeypatch):
    import threading
    import time

    monkeypatch.setattr("app.providers.transcribe._WHISPER", {})
    geladen = []

    class FakeModell:
        def transcribe(self, pfad, **kwargs):
            return iter([]), None

    def lader(modell, root):
        geladen.append((modell, root))
        time.sleep(0.1)
        return FakeModell()

    monkeypatch.setattr("app.providers.transcribe._lade_whisper", lader)
    threads = [
        threading.Thread(target=lambda: LokalerTranskribierer("small", "/w").transkribieren(b"x", "a.wav"))
        for _ in range(3)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert geladen == [("small", "/w")]
