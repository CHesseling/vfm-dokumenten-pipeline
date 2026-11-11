from fastapi.testclient import TestClient

from app.main import create_app


def test_gesundheit():
    with TestClient(create_app()) as client:
        antwort = client.get("/gesundheit")

    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}


def test_static_und_vorlagen_unabhaengig_vom_arbeitsverzeichnis(tmp_path, monkeypatch):
    import subprocess
    import sys

    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "c = TestClient(create_app())\n"
        "print(c.get('/static/ndr-logo.png').status_code)\n"
    )
    repo = __import__("pathlib").Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(repo), "DATABASE_URL": "x"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "200"
