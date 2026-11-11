"""End-to-End: Mini-Beispielsatz durch die ganze Pipeline gegen echte lokale Modelle.

Braucht: laufendes Ollama (chat/vision/embed), die Modellordner unter spike/models/
(Whisper, Docling, HF-Cache fuer GliNER und Reranker) und die Test-Datenbank.
Start: uv run pytest -m modelle tests/test_e2e.py -v
"""

from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from typer.testing import CliRunner

import app.cli as cli
from app.config import Settings
from app.enums import AnalyseArt, DokumentTyp, NerMethode
from app.models import Analyse, Dokument, Entitaet, TextExtraktion

pytestmark = pytest.mark.modelle

ROOT = Path(__file__).resolve().parent.parent
MINI = ROOT / "tests" / "fixtures" / "mini"
SPIKE = ROOT / "spike" / "models"
OLLAMA = "http://localhost:11434/v1"

runner = CliRunner(env={"COLUMNS": "250"})


@pytest.fixture
def e2e_settings(engine, tmp_path, monkeypatch):
    try:
        antwort = httpx.get("http://localhost:11434/api/tags", timeout=3)
        antwort.raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Ollama nicht erreichbar")
    vorhanden = {m["name"] for m in antwort.json().get("models", [])}
    fehlend = [
        m for m in ("qwen3.5:4b", "qwen3-vl:8b", "bge-m3")
        if m not in vorhanden and f"{m}:latest" not in vorhanden
    ]
    if fehlend:
        pytest.skip(f"Ollama-Modelle fehlen: {', '.join(fehlend)}")
    for ordner in ("whisper", "docling", "hf"):
        if not (SPIKE / ordner).is_dir():
            pytest.skip(f"Modellordner spike/models/{ordner} fehlt")
    if not (MINI / "mail.eml").exists():
        pytest.skip("Mini-Fixtures fehlen - scripts/fixtures_erzeugen.py ausfuehren")

    monkeypatch.setenv("HF_HOME", str(SPIKE / "hf"))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    from tests.conftest import TEST_DATABASE_URL

    return Settings(
        _env_file=None,
        provider="ollama",
        database_url=TEST_DATABASE_URL,
        daten_pfad=str(tmp_path),
        chat_base_url=OLLAMA,
        chat_model="qwen3.5:4b",
        chat_extra_body={"reasoning_effort": "none"},
        vision_base_url=OLLAMA,
        vision_model="qwen3-vl:8b",
        vision_extra_body={"think": False},
        embed_base_url=OLLAMA,
        embed_model="bge-m3",
        rerank_backend="local",
        transcribe_backend="local",
        whisper_pfad=str(SPIKE / "whisper"),
        docling_artifacts_pfad=str(SPIKE / "docling"),
    )


def test_mini_beispielsatz_ganze_pipeline(e2e_settings, session):
    s = e2e_settings

    r = runner.invoke(cli.app, ["pipeline", str(MINI)], obj=s)
    assert r.exit_code == 0, r.output
    print(r.output)

    # 5 Dateien; vertrag.pdf als Mail-Anhang wird per SHA dedupliziert
    dokumente = session.exec(select(Dokument)).scalars().all()
    namen = sorted(d.dateiname for d in dokumente)
    assert namen == ["foto.jpg", "mail.eml", "scan.pdf", "sprachnachricht.m4a", "vertrag.pdf"], namen
    vertrag = next(d for d in dokumente if d.dateiname == "vertrag.pdf")
    foto = next(d for d in dokumente if d.dateiname == "foto.jpg")
    assert sum(1 for d in dokumente if d.sha256 == vertrag.sha256) == 1

    # NER: IBAN per Muster aus dem Vertragstext
    extraktion = session.exec(
        select(TextExtraktion).where(TextExtraktion.dokument_id == vertrag.id, TextExtraktion.ist_aktiv.is_(True))
    ).scalars().one()
    ibans = session.exec(
        select(Entitaet).where(
            Entitaet.textextraktion_id == extraktion.id,
            Entitaet.methode == NerMethode.MUSTER,
            Entitaet.label == "iban",
        )
    ).scalars().all()
    assert any(e.normalisiert == "DE89370400440532013000" for e in ibans), [(e.text, e.normalisiert) for e in ibans]

    # Audio: Transkript existiert (Telefonnummer-Ziffern variieren je nach Whisper-Lauf, daher nicht hart geprueft)
    audio = next(d for d in dokumente if d.typ == DokumentTyp.AUDIO)
    transkript = session.exec(
        select(TextExtraktion).where(TextExtraktion.dokument_id == audio.id, TextExtraktion.ist_aktiv.is_(True))
    ).scalars().one()
    print("Whisper-Transkript:", transkript.text)
    assert transkript.text.strip()

    # Suche findet das Foto (Schild "Lagerhalle 7")
    r = runner.invoke(cli.app, ["suche", "Lagerhalle"], obj=s)
    assert r.exit_code == 0, r.output
    print(r.output)
    assert "foto.jpg" in r.output
    # Rang 1 zaehlt: mit --top-k 1 darf nur das Foto erscheinen
    r = runner.invoke(cli.app, ["suche", "Lagerhalle", "--top-k", "1"], obj=s)
    assert r.exit_code == 0, r.output
    print(r.output)
    assert "foto.jpg" in r.output
    for anderer in ("mail.eml", "scan.pdf", "vertrag.pdf", "sprachnachricht.m4a"):
        assert anderer not in r.output

    # RAG-Antwort nennt den Vertragswert
    r = runner.invoke(cli.app, ["frage", "Wie hoch ist der Vertragswert?"], obj=s)
    assert r.exit_code == 0, r.output
    print(r.output)
    assert "12.500" in r.output or "12500" in r.output

    # Klassifikation des Vertrags
    session.expire_all()
    klassifikation = session.exec(
        select(Analyse).where(Analyse.dokument_id == vertrag.id, Analyse.art == AnalyseArt.KLASSIFIKATION)
    ).scalars().one()
    print("Klassifikation:", klassifikation.ergebnis)
    assert klassifikation.ergebnis["kategorie"] == "Vertrag"

    # Bildbeschreibung fuer das Foto liegt vor
    beschreibung = session.exec(
        select(Analyse).where(Analyse.dokument_id == foto.id, Analyse.art == AnalyseArt.BILDBESCHREIBUNG)
    ).scalars().one()
    print("Bildbeschreibung:", beschreibung.ergebnis)
