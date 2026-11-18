from pathlib import Path
from fastapi.testclient import TestClient

from app.main import create_app


def test_gesundheit():
    with TestClient(create_app()) as client:
        antwort = client.get("/gesundheit")

    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}


def test_vorlagen_unabhaengig_vom_arbeitsverzeichnis(tmp_path, monkeypatch):
    import subprocess
    import sys

    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "from app.web.vorlagen import templates\n"
        "TestClient(create_app())\n"
        "print(templates.get_template('base.html').name)\n"
    )
    repo = __import__("pathlib").Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(repo), "DATABASE_URL": "x"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "base.html"


def test_kein_ndr_logo():
    from fastapi.testclient import TestClient

    from app.main import create_app

    c = TestClient(create_app())
    assert c.get("/static/ndr-logo.png").status_code == 404
    basis = (Path(__file__).resolve().parent.parent / "app/web/templates/base.html").read_text()
    assert "ndr-logo" not in basis
