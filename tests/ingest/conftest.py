import pytest

from app.config import Settings


@pytest.fixture
def einstellungen(tmp_path):
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://x/x",
        chat_base_url="x",
        chat_model="x",
        embed_base_url="x",
        embed_model="x",
        daten_pfad=str(tmp_path),
    )
