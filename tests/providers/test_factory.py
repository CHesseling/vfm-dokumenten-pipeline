import pytest

from app.config import Settings
from app.providers import factory
from app.providers.rerank import ApiReranker, KeinReranker, LokalerReranker
from app.providers.transcribe import ApiTranskribierer, LokalerTranskribierer


def _settings(**kw) -> Settings:
    basis = dict(
        database_url="postgresql+psycopg://x/y",
        chat_base_url="http://chat/v1",
        chat_model="chat-m",
        embed_base_url="http://embed/v1",
        embed_model="embed-m",
        _env_file=None,
    )
    return Settings(**(basis | kw))


def test_factory_rerank_backends():
    assert isinstance(factory.reranker(_settings(rerank_backend="local")), LokalerReranker)
    assert isinstance(factory.reranker(_settings(rerank_backend="none")), KeinReranker)
    api = factory.reranker(_settings(rerank_backend="api", rerank_base_url="http://r/v1"))
    assert isinstance(api, ApiReranker)
    with pytest.raises(ValueError, match="RERANK_BASE_URL fehlt für RERANK_BACKEND=api"):
        factory.reranker(_settings(rerank_backend="api"))


def test_factory_vision_nutzt_chat_fallback():
    s = _settings(chat_api_key="k", chat_extra_body={"a": 1})
    c = factory.vision_client(s)
    assert (c.model, c.rolle, c._base_url) == ("chat-m", "vision", "http://chat/v1")
    assert c._extra_body == {"a": 1}
    assert c._client.headers["authorization"] == "Bearer k"


def test_factory_vision_eigenes_modell():
    s = _settings(
        vision_base_url="http://v/v1", vision_model="vm", chat_extra_body={"a": 1}, vision_extra_body={"b": 2}
    )
    c = factory.vision_client(s)
    assert (c.model, c._base_url, c._extra_body) == ("vm", "http://v/v1", {"b": 2})
    ohne = factory.vision_client(s.model_copy(update={"vision_extra_body": {}}))
    assert ohne._extra_body == {}


def test_factory_chat_und_embedding():
    s = _settings(chat_extra_body={"x": 1}, embed_batch=7, provider="cortecs", cortecs_api_key="ck")
    c = factory.chat_client(s)
    assert c.model == "chat-m" and c._extra_body == {"x": 1} and c.rolle == "chat"
    assert c._client.headers["authorization"] == "Bearer ck"
    e = factory.embedding_client(s)
    assert e.model == "embed-m" and e._batch == 7


def test_factory_transkribierer():
    assert isinstance(factory.transkribierer(_settings()), LokalerTranskribierer)
    api = factory.transkribierer(_settings(transcribe_backend="api", transcribe_base_url="http://t/v1"))
    assert isinstance(api, ApiTranskribierer)
    with pytest.raises(ValueError, match="TRANSCRIBE_BASE_URL"):
        factory.transkribierer(_settings(transcribe_backend="api"))
