import subprocess
import sys
import threading
import time

import pytest

from app.modell_sperre import modell_sperre


@pytest.fixture(autouse=True)
def eigene_sperrdatei(tmp_path, monkeypatch):
    monkeypatch.setenv("VFM_MODELL_SPERRE", str(tmp_path / "modelle.lock"))
    return tmp_path / "modelle.lock"


def test_threads_laufen_nacheinander():
    ablauf: list[str] = []

    def arbeit(name: str) -> None:
        with modell_sperre(name):
            ablauf.append(f"{name}-start")
            time.sleep(0.2)
            ablauf.append(f"{name}-ende")

    erster = threading.Thread(target=arbeit, args=("a",))
    erster.start()
    time.sleep(0.05)
    zweiter = threading.Thread(target=arbeit, args=("b",))
    zweiter.start()
    erster.join()
    zweiter.join()
    assert ablauf == ["a-start", "a-ende", "b-start", "b-ende"]


def test_anderer_prozess_wartet(eigene_sperrdatei):
    versuch = (
        "import fcntl, sys\n"
        "f = open(sys.argv[1], 'a')\n"
        "try:\n"
        "    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n"
        "    sys.exit(3)\n"
    )
    with modell_sperre("test"):
        belegt = subprocess.run([sys.executable, "-c", versuch, str(eigene_sperrdatei)])
    frei = subprocess.run([sys.executable, "-c", versuch, str(eigene_sperrdatei)])
    assert belegt.returncode == 3
    assert frei.returncode == 0


def test_fremde_sperrdatei_ohne_schreibrecht(eigene_sperrdatei):
    # z. B. von `sudo vfm ...` im Browser-Terminal als root angelegt (0644)
    eigene_sperrdatei.touch()
    eigene_sperrdatei.chmod(0o444)
    with modell_sperre("test"):
        pass


def test_sperre_wird_bei_fehler_freigegeben():
    with pytest.raises(RuntimeError):
        with modell_sperre("test"):
            raise RuntimeError("kaputt")
    with modell_sperre("test"):  # wuerde sonst ewig warten
        pass
