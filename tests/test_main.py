from fastapi.testclient import TestClient

from app.main import create_app


def test_gesundheit():
    with TestClient(create_app()) as client:
        antwort = client.get("/gesundheit")

    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}
