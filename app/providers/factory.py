from app.config import Settings
from app.providers.embeddings import EmbeddingClient
from app.providers.llm_client import LLMClient
from app.providers.rerank import ApiReranker, KeinReranker, LokalerReranker, Reranker
from app.providers.transcribe import ApiTranskribierer, LokalerTranskribierer, Transkribierer


def chat_client(s: Settings) -> LLMClient:
    return LLMClient(
        base_url=s.chat_base_url,
        model=s.chat_model,
        api_key=s.api_key_fuer("chat"),
        gesamt_timeout=s.chat_timeout_sekunden,
        structured_outputs=s.chat_structured_outputs,
        extra_body=s.chat_extra_body,
        rolle="chat",
    )


def vision_client(s: Settings) -> LLMClient:
    base_url, model, key = s.vision_effektiv()
    if s.vision_extra_body:
        extra = s.vision_extra_body
    elif not s.vision_model:
        extra = s.chat_extra_body  # Fallback auf das Chat-Modell
    else:
        extra = {}
    return LLMClient(
        base_url=base_url,
        model=model,
        api_key=key,
        gesamt_timeout=s.chat_timeout_sekunden,
        structured_outputs=s.chat_structured_outputs,
        extra_body=extra,
        rolle="vision",
    )


def embedding_client(s: Settings) -> EmbeddingClient:
    return EmbeddingClient(
        base_url=s.embed_base_url,
        model=s.embed_model,
        api_key=s.api_key_fuer("embed"),
        batch=s.embed_batch,
    )


def reranker(s: Settings) -> Reranker:
    if s.rerank_backend == "none":
        return KeinReranker()
    if s.rerank_backend == "api":
        if not s.rerank_base_url:
            raise ValueError("RERANK_BASE_URL fehlt für RERANK_BACKEND=api")
        return ApiReranker(s.rerank_base_url, s.rerank_model, s.api_key_fuer("rerank"))
    return LokalerReranker(s.rerank_model)


def transkribierer(s: Settings) -> Transkribierer:
    if s.transcribe_backend == "api":
        if not s.transcribe_base_url:
            raise ValueError("TRANSCRIBE_BASE_URL fehlt für TRANSCRIBE_BACKEND=api")
        return ApiTranskribierer(s.transcribe_base_url, s.transcribe_model, s.api_key_fuer("transcribe"))
    return LokalerTranskribierer(s.transcribe_model, s.whisper_pfad)
