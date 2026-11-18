import shutil
from pathlib import Path

import pytest

from app.config import Settings, lade_settings

OLLAMA = (
    "CHAT_BASE_URL=http://ollama/v1\nCHAT_MODEL=m-ollama\n"
    "EMBED_BASE_URL=http://ollama/v1\nEMBED_MODEL=bge-m3\n"
)
CORTECS = (
    "CHAT_BASE_URL=https://api.cortecs.ai/v1\nCHAT_MODEL=m-cortecs\n"
    "EMBED_BASE_URL=https://api.cortecs.ai/v1\nEMBED_MODEL=bge-m3\n"
)


def _env_isolieren(monkeypatch) -> None:
    """Entfernt jede Umgebungsvariable, die ein Settings-Feld befuellen koennte."""
    namen = {n.upper() for n in Settings.model_fields} | {"PROVIDER", "CORTECS_API_KEY"}
    for var in namen:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def arbeitsordner(tmp_path, monkeypatch):
    import app.config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app.config, "REPO_ROOT", tmp_path)
    _env_isolieren(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "ollama.env").write_text(OLLAMA)
    (tmp_path / "profile" / "cortecs.env").write_text(CORTECS)
    return tmp_path


def _env(pfad: Path, inhalt: str) -> None:
    (pfad / ".env").write_text(inhalt)


def test_profil_ollama_ist_default(arbeitsordner):
    s = lade_settings()
    assert s.provider == "ollama"
    assert s.chat_base_url == "http://ollama/v1"


def test_provider_argument_schlaegt_env(arbeitsordner):
    _env(arbeitsordner, "PROVIDER=ollama\n")
    s = lade_settings("cortecs")
    assert s.provider == "cortecs"
    assert s.chat_base_url == "https://api.cortecs.ai/v1"


def test_provider_aus_env_datei(arbeitsordner):
    _env(arbeitsordner, "PROVIDER=cortecs\n")
    assert lade_settings().chat_base_url == "https://api.cortecs.ai/v1"


def test_env_ueberschreibt_profil(arbeitsordner):
    _env(arbeitsordner, "CHAT_MODEL=x\n")
    assert lade_settings().chat_model == "x"


def test_cortecs_key_als_fallback(arbeitsordner):
    _env(arbeitsordner, "CORTECS_API_KEY=k\n")
    assert lade_settings("cortecs").api_key_fuer("embed") == "k"
    assert lade_settings("ollama").api_key_fuer("embed") is None


def test_rollen_key_schlaegt_cortecs_key(arbeitsordner):
    _env(arbeitsordner, "CORTECS_API_KEY=k\nEMBED_API_KEY=e\n")
    assert lade_settings("cortecs").api_key_fuer("embed") == "e"


def test_vision_faellt_auf_chat_zurueck(arbeitsordner):
    _env(arbeitsordner, "CHAT_API_KEY=ck\n")
    s = lade_settings()
    assert s.vision_effektiv() == ("http://ollama/v1", "m-ollama", "ck")


def test_vision_eigene_werte(arbeitsordner):
    _env(arbeitsordner, "VISION_BASE_URL=http://v/v1\nVISION_MODEL=vm\nVISION_API_KEY=vk\n")
    assert lade_settings().vision_effektiv() == ("http://v/v1", "vm", "vk")


def test_unbekannter_provider(arbeitsordner):
    with pytest.raises(ValueError, match="erlaubt: ollama, cortecs"):
        lade_settings("foo")


def test_leere_optionale_felder_sind_none(arbeitsordner):
    _env(arbeitsordner, "RERANK_BASE_URL=\n")
    assert lade_settings().rerank_base_url is None


def test_json_felder_und_defaults(arbeitsordner):
    _env(arbeitsordner, 'CHAT_EXTRA_BODY={"reasoning_effort":"none"}\nVISION_EXTRA_BODY={"think":false}\n')
    s = lade_settings()
    assert s.chat_extra_body == {"reasoning_effort": "none"}
    assert s.vision_extra_body == {"think": False}
    assert s.whisper_pfad == "/models/whisper"
    assert s.rag_top_k == 8


def test_echte_profile_laden(monkeypatch, tmp_path):
    repo = Path(__file__).resolve().parent.parent
    # Profile in ein leeres Verzeichnis kopieren: die echte .env des Entwicklers
    # darf nicht gelesen werden.
    shutil.copytree(repo / "profile", tmp_path / "profile")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.config.REPO_ROOT", tmp_path)
    _env_isolieren(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "x")
    o = lade_settings("ollama")
    assert o.chat_model == "qwen3.5:4b"
    assert o.vision_model == "qwen3-vl:8b"
    assert o.chat_extra_body == {"reasoning_effort": "none"}
    c = lade_settings("cortecs")
    assert c.rerank_backend == "local" and c.transcribe_backend == "local"
    assert c.transcribe_model == "small"


def test_vision_key_cortecs_fallback(arbeitsordner):
    _env(arbeitsordner, "CORTECS_API_KEY=k\n")
    assert lade_settings("cortecs").vision_effektiv()[2] == "k"
    assert lade_settings("ollama").vision_effektiv()[2] is None


def test_profile_unabhaengig_vom_arbeitsverzeichnis(tmp_path, monkeypatch):
    """Aus einem fremden Ordner (ohne profile/ und .env) wird das Profil des Repos gefunden."""
    import app.config as config

    monkeypatch.chdir(tmp_path)
    _env_isolieren(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    assert (config.REPO_ROOT / "profile" / "ollama.env").is_file()
    s = lade_settings("ollama")
    assert s.provider == "ollama"
    assert s.chat_base_url and s.embed_model  # Pflichtfelder kommen aus profile/ollama.env


def test_kategorien_pfad_relativ_zum_repo(tmp_path, monkeypatch):
    from app.analyse.kategorien import lade_kategorien

    monkeypatch.chdir(tmp_path)
    assert lade_kategorien("config/kategorien.yaml")


def test_env_aus_repo_wenn_keine_im_arbeitsverzeichnis(arbeitsordner, tmp_path, monkeypatch):
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    _env(arbeitsordner, "CHAT_MODEL=aus-repo\n")
    monkeypatch.chdir(fremd)
    assert lade_settings().chat_model == "aus-repo"


def test_gliner_schwelle_default():
    assert Settings(database_url="postgresql+psycopg://x/y", chat_base_url="http://c/v1", chat_model="c",
                    embed_base_url="http://e/v1", embed_model="e", _env_file=None).gliner_schwelle == 0.5
