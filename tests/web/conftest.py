import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from tests.conftest import TEST_DATABASE_URL


@pytest.fixture
def einstellungen(tmp_path):
    return Settings(
        database_url=TEST_DATABASE_URL,
        daten_pfad=str(tmp_path / "daten"),
        material_pfad=str(tmp_path / "material"),
        chat_base_url="http://chat/v1",
        chat_model="chat-m",
        embed_base_url="http://embed/v1",
        embed_model="embed-m",
        rerank_backend="none",
        transcribe_backend="api",
        transcribe_base_url="http://tr/v1",
        _env_file=None,
    )


@pytest.fixture
def client(session, einstellungen):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_settings] = lambda: einstellungen
    with TestClient(app, follow_redirects=False) as c:
        yield c
