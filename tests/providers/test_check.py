import httpx
import pytest
import respx

from app.config import Settings
from app.providers import check as check_modul
from app.providers.check import pruefe_rollen


def _settings(**kw) -> Settings:
    basis = dict(
        database_url="postgresql+psycopg://x/y",
        chat_base_url="http://chat/v1",
        chat_model="chat-m",
        embed_base_url="http://embed/v1",
        embed_model="embed-m",
        rerank_backend="none",
        transcribe_backend="api",
        transcribe_base_url="http://tr/v1",
        transcribe_model="w",
        _env_file=None,
    )
    return Settings(**(basis | kw))


def _chat_ok(base="http://chat/v1"):
    respx.post(f"{base}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    )


def _embed_ok():
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
    )


def _nach_rolle(ergebnisse):
    return {e.rolle: e for e in ergebnisse}


@respx.mock
def test_alles_ok():
    _chat_ok()
    _embed_ok()
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    erg = _nach_rolle(pruefe_rollen(_settings()))
    assert set(erg) == {"chat", "vision", "embed", "rerank", "transcribe"}
    assert all(e.ok for e in erg.values()), erg
    assert erg["embed"].detail == "Dimension 3"
    assert erg["chat"].modell == "chat-m"


@respx.mock
def test_chat_nicht_erreichbar_andere_laufen_weiter():
    respx.post("http://chat/v1/chat/completions").mock(side_effect=httpx.ConnectError("x"))
    _embed_ok()
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))
    erg = _nach_rolle(pruefe_rollen(_settings()))
    assert not erg["chat"].ok and "nicht erreichbar" in erg["chat"].detail
    assert not erg["vision"].ok
    assert erg["embed"].ok


@respx.mock
def test_vision_sendet_bild():
    route = respx.post("http://chat/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "weiß"}}]})
    )
    _embed_ok()
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))
    pruefe_rollen(_settings())
    bodies = [r.request.content.decode() for r in route.calls]
    assert any("data:image/png;base64," in b for b in bodies)


@respx.mock
def test_rerank_api_httpfehler_und_transcribe_http_status(monkeypatch):
    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    _chat_ok()
    _embed_ok()
    respx.post("http://rr/v1/rerank").mock(return_value=httpx.Response(500))
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(401))
    s = _settings(rerank_backend="api", rerank_base_url="http://rr/v1")
    erg = _nach_rolle(pruefe_rollen(s))
    assert not erg["rerank"].ok and "Serverfehler 500" in erg["rerank"].detail
    assert not erg["transcribe"].ok and "HTTP 401" in erg["transcribe"].detail


@respx.mock
def test_api_rerank_nicht_erreichbar():
    _chat_ok()
    _embed_ok()
    respx.post("http://rr/v1/rerank").mock(side_effect=httpx.ConnectError("x"))
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))
    s = _settings(rerank_backend="api", rerank_base_url="http://rr/v1")
    assert "nicht erreichbar" in _nach_rolle(pruefe_rollen(s))["rerank"].detail


@respx.mock
def test_rerank_lokal_nutzt_reranker(monkeypatch):
    _chat_ok()
    _embed_ok()
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))

    class Fake:
        def rerank(self, frage, texte):
            return [(0, 1.0), (1, 0.5)]

    monkeypatch.setattr(check_modul.factory, "reranker", lambda s: Fake())
    assert _nach_rolle(pruefe_rollen(_settings(rerank_backend="local")))["rerank"].ok


@respx.mock
def test_rerank_lokal_fehler(monkeypatch):
    _chat_ok()
    _embed_ok()
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))

    class Kaputt:
        def rerank(self, frage, texte):
            raise OSError("Modell nicht im Cache")

    monkeypatch.setattr(check_modul.factory, "reranker", lambda s: Kaputt())
    r = _nach_rolle(pruefe_rollen(_settings(rerank_backend="local")))["rerank"]
    assert not r.ok and "Modell nicht im Cache" in r.detail


@respx.mock
def test_transcribe_lokal_ordner(tmp_path):
    _chat_ok()
    _embed_ok()
    s = _settings(transcribe_backend="local", transcribe_base_url=None, whisper_pfad=str(tmp_path / "w"))
    r = _nach_rolle(pruefe_rollen(s))["transcribe"]
    assert not r.ok and str(tmp_path / "w") in r.detail
    (tmp_path / "w").mkdir()
    assert not _nach_rolle(pruefe_rollen(s))["transcribe"].ok  # leer
    (tmp_path / "w" / "model.bin").write_text("x")
    r = _nach_rolle(pruefe_rollen(s))["transcribe"]
    assert r.ok and str(tmp_path / "w") in r.detail
