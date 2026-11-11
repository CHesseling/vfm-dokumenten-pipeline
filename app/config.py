import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDER_ERLAUBT = ("ollama", "cortecs")

# Pfade relativ zum Paket aufloesen, nicht zum Arbeitsverzeichnis: `vfm` laeuft
# auch aus anderen Ordnern (z. B. ueber den Konsolen-Einstiegspunkt).
PAKET = Path(__file__).resolve().parent
REPO_ROOT = PAKET.parent


def repo_pfad(pfad: str | Path) -> Path:
    """Relative Pfade gelten ab dem Repo-Root (im Image: /app)."""
    pfad = Path(pfad)
    return pfad if pfad.is_absolute() else REPO_ROOT / pfad


def _env_datei() -> Path:
    """`.env` aus dem Arbeitsverzeichnis, sonst die im Repo-Root."""
    lokal = Path(".env")
    return lokal if lokal.is_file() else REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    sql_readonly_url: str | None = None
    daten_pfad: str = "/data/dateien"
    material_pfad: str = "/material"
    log_level: str = "INFO"
    provider: str = "ollama"
    api_token: str | None = None
    cortecs_api_key: str | None = None

    chat_base_url: str
    chat_model: str
    chat_api_key: str | None = None
    chat_timeout_sekunden: float = 600.0
    chat_structured_outputs: bool = True
    chat_extra_body: dict = {}

    vision_base_url: str | None = None
    vision_model: str | None = None
    vision_api_key: str | None = None
    vision_extra_body: dict = {}

    embed_base_url: str
    embed_model: str
    embed_api_key: str | None = None
    embed_batch: int = 32

    rerank_backend: Literal["local", "api", "none"] = "local"
    rerank_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    rerank_base_url: str | None = None
    rerank_api_key: str | None = None

    transcribe_backend: Literal["local", "api"] = "local"
    transcribe_model: str = "small"
    transcribe_base_url: str | None = None
    transcribe_api_key: str | None = None
    whisper_pfad: str = "/models/whisper"

    gliner_model: str = "fastino/gliner2-base-v1"
    docling_artifacts_pfad: str = "/models/docling"

    chunk_zeichen: int = 1500
    chunk_ueberlappung: int = 200
    rag_top_n: int = 50
    rag_top_k: int = 8
    kategorien_pfad: str = "config/kategorien.yaml"

    @field_validator("*", mode="before")
    @classmethod
    def _leere_zeichenkette_als_none(cls, wert, info):
        # Konvention: eine leer gelassene Variable ("RERANK_BASE_URL=") heisst
        # "nicht gesetzt". Nur fuer optionale Felder (Default None) - bei
        # Pflichtfeldern und Feldern mit Default bleibt "" ein echter Wert.
        if wert == "" and cls.model_fields[info.field_name].default is None:
            return None
        return wert

    def api_key_fuer(self, rolle: str) -> str | None:
        eigener = getattr(self, f"{rolle}_api_key")
        if eigener:
            return eigener
        if self.provider == "cortecs":
            return self.cortecs_api_key
        return None

    def vision_effektiv(self) -> tuple[str, str, str | None]:
        return (
            self.vision_base_url or self.chat_base_url,
            self.vision_model or self.chat_model,
            self.api_key_fuer("vision") or self.api_key_fuer("chat"),
        )


def lade_settings(provider: str | None = None) -> Settings:
    if provider is None:
        provider = (
            os.environ.get("PROVIDER")
            or dotenv_values(_env_datei()).get("PROVIDER")
            or "ollama"
        )
    if provider not in PROVIDER_ERLAUBT:
        raise ValueError(
            f"Unbekannter Provider '{provider}' – erlaubt: {', '.join(PROVIDER_ERLAUBT)}"
        )
    return Settings(
        _env_file=(REPO_ROOT / "profile" / f"{provider}.env", _env_datei()),
        provider=provider,
    )


@lru_cache
def get_settings() -> Settings:
    return lade_settings()
