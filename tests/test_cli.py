import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

import app.cli as cli
from app.config import Settings
from app.providers.llm_client import ProviderFehler

runner = CliRunner()


@pytest.fixture
def cli_settings(engine):
    from tests.conftest import TEST_DATABASE_URL

    return Settings(
        database_url=TEST_DATABASE_URL,
        sql_readonly_url=TEST_DATABASE_URL,
        chat_base_url="http://chat/v1",
        chat_model="chat-m",
        embed_base_url="http://embed/v1",
        embed_model="embed-m",
        rerank_backend="none",
        transcribe_backend="api",
        transcribe_base_url="http://tr/v1",
        _env_file=None,
    )


def _mocks(chat_fehler=False):
    if chat_fehler:
        respx.post("http://chat/v1/chat/completions").mock(side_effect=httpx.ConnectError("x"))
    else:
        respx.post("http://chat/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        )
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
    )
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))


@respx.mock
def test_check_alles_ok(cli_settings):
    _mocks()
    r = runner.invoke(cli.app, ["check"], obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert "Dimension 3" in r.output


@respx.mock
def test_check_ollama_aus(cli_settings):
    _mocks(chat_fehler=True)
    r = runner.invoke(cli.app, ["check"], obj=cli_settings)
    assert r.exit_code == 1
    assert "chat" in r.output and "nicht erreichbar" in r.output
    assert "Traceback" not in r.output


def test_status_leer(cli_settings, session):
    r = runner.invoke(cli.app, ["status"], obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert "pdf" in r.output and "0" in r.output
    assert "Traceback" not in r.output


def test_status_zaehlt(cli_settings, session):
    from app.enums import DokumentTyp, ExtraktionsMethode
    from app.models import Chunk, Dokument, Embedding, TextExtraktion

    d = Dokument(sha256="a", dateiname="a.pdf", typ=DokumentTyp.PDF, mime="application/pdf", groesse=1)
    session.add(d)
    session.commit()
    te = TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.SCHNELL, text="x", ist_aktiv=True)
    session.add(te)
    session.commit()
    c = Chunk(textextraktion_id=te.id, position=0, start=0, ende=1, text="x")
    session.add(c)
    session.commit()
    session.add(Embedding(chunk_id=c.id, modell="embed-m", vektor=[0.1, 0.2, 0.3]))
    session.add(Embedding(chunk_id=c.id, modell="alt", vektor=[0.1, 0.2, 0.3]))
    session.commit()
    r = runner.invoke(cli.app, ["status"], obj=cli_settings)
    assert r.exit_code == 0, r.output
    zeile = next(z for z in r.output.splitlines() if "pdf" in z)
    zahlen = [z.strip() for z in zeile.split("│") if z.strip().isdigit()]
    assert zahlen == ["1", "1", "0", "1", "0"]


def test_providerfehler_exitcode_2(cli_settings):
    @cli.app.command("boom-test")
    @cli.cli_fehler
    def boom(ctx: typer.Context):
        raise ProviderFehler("chat", "http://x/v1", "m", "nicht erreichbar")

    try:
        r = runner.invoke(cli.app, ["boom-test"], obj=cli_settings)
    finally:
        cli.app.registered_commands[:] = [c for c in cli.app.registered_commands if c.name != "boom-test"]
    assert r.exit_code == 2
    assert "nicht erreichbar" in r.output
    assert "Traceback" not in r.output


def test_unvollstaendige_konfiguration(tmp_path, monkeypatch):
    from app.config import Settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.config.REPO_ROOT", tmp_path)
    for n in {n.upper() for n in Settings.model_fields} | {"PROVIDER", "CORTECS_API_KEY"}:
        monkeypatch.delenv(n, raising=False)
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "ollama.env").write_text("CHAT_BASE_URL=http://x/v1\nEMBED_BASE_URL=http://x/v1\nEMBED_MODEL=e\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/d")
    r = runner.invoke(cli.app, ["status"])
    assert r.exit_code == 2
    assert "Konfiguration unvollständig" in r.output and "CHAT_MODEL" in r.output
    assert "Traceback" not in r.output and "validation error" not in r.output


def test_providerfehler_mit_markup_zeichen(cli_settings):
    @cli.app.command("markup-test")
    @cli.cli_fehler
    def boom(ctx: typer.Context):
        raise ProviderFehler("chat", "http://x/v1", "m", "kaputt [/foo] [bold]")

    try:
        r = runner.invoke(cli.app, ["markup-test"], obj=cli_settings)
    finally:
        cli.app.registered_commands[:] = [c for c in cli.app.registered_commands if c.name != "markup-test"]
    assert r.exit_code == 2
    assert "[/foo]" in r.output and "Traceback" not in r.output


@respx.mock
def test_check_detail_mit_markup(cli_settings):
    respx.post("http://chat/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "[/foo]"}}]})
    )
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})
    )
    respx.get("http://tr/v1/models").mock(return_value=httpx.Response(200))
    r = runner.invoke(cli.app, ["check"], obj=cli_settings)
    assert r.exit_code == 0 and "[/foo]" in r.output and "Traceback" not in r.output


def test_vfm_ingest_ordner(cli_settings, session, tmp_path):
    cli_settings.daten_pfad = str(tmp_path / "daten")
    ordner = tmp_path / "m"
    ordner.mkdir()
    (ordner / "a.txt").write_text("Text eins, lang genug für die Extraktion.")
    (ordner / "b.txt").write_text("Text zwei, ebenfalls lang genug dafür.")
    r = runner.invoke(cli.app, ["ingest", str(ordner)], obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert "neu: 2" in r.output and "bekannt: 0" in r.output and "fehler: 0" in r.output


def test_vfm_text_vergleich(cli_settings, session):
    from app.enums import DokumentTyp, ExtraktionsMethode
    from app.models import Dokument, TextExtraktion

    d = Dokument(sha256="b", dateiname="a.pdf", typ=DokumentTyp.PDF, mime="application/pdf", groesse=1)
    session.add(d)
    session.commit()
    session.add(TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.SCHNELL, text="Schnelltext", ist_aktiv=True))
    session.add(TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.DOCLING, text="Doclingtext", modell="docling"))
    session.commit()
    r = runner.invoke(cli.app, ["text", str(d.id), "--vergleich"], obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert "schnell" in r.output and "docling" in r.output
    assert "Schnelltext" in r.output and "Doclingtext" in r.output
    r = runner.invoke(cli.app, ["text", str(d.id)], obj=cli_settings)
    assert "Schnelltext" in r.output
    r = runner.invoke(cli.app, ["text", str(d.id), "--aktiv", "docling"], obj=cli_settings)
    assert r.exit_code == 0 and "Doclingtext" in r.output
    r = runner.invoke(cli.app, ["text", "99999"], obj=cli_settings)
    assert r.exit_code == 1 and "nicht gefunden" in r.output


def test_sql_befehl_zeigt_tabelle(cli_settings):
    r = runner.invoke(cli.app, ["sql", "SELECT 7 AS zahl"], obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert "zahl" in r.output and "7" in r.output


def test_sql_befehl_fehler_exit_1(cli_settings):
    r = runner.invoke(cli.app, ["sql", "DELETE FROM lauf"], obj=cli_settings)
    assert r.exit_code == 1
    assert "read-only" in r.output


def test_vfm_ner_muster_und_vergleich(cli_settings, session):
    from app.enums import DokumentTyp, ExtraktionsMethode
    from app.models import Dokument, TextExtraktion

    d = Dokument(sha256="n1", dateiname="n.txt", typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    session.add(TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT,
                               text="Konto DE89 3704 0044 0532 0130 00", ist_aktiv=True))
    session.commit()
    r = runner.invoke(cli.app, ["ner", "--methode", "muster", "--dokument", str(d.id), "--vergleich"],
                      obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert "iban" in r.output and "✓" in r.output


def test_vfm_ner_vergleich_ohne_dokument(cli_settings):
    r = runner.invoke(cli.app, ["ner", "--vergleich"], obj=cli_settings)
    assert r.exit_code == 2


def test_vfm_ner_unbekannte_methode(cli_settings):
    r = runner.invoke(cli.app, ["ner", "--methode", "quark"], obj=cli_settings)
    assert r.exit_code == 2


@pytest.mark.parametrize("args", [["--labels", "a=b=c"], ["--schwelle", "1.5"]])
def test_vfm_ner_parameter_ungueltig(cli_settings, args):
    r = runner.invoke(cli.app, ["ner", *args], obj=cli_settings)
    assert r.exit_code == 2


def test_vfm_ner_reicht_labels_und_schwelle_durch(cli_settings, monkeypatch):
    import app.ner.ablauf as ablauf
    from app.ner.ablauf import NerBilanz
    from app.ner.labels import labels_parsen

    erhalten = {}

    def fake(session, s, methoden, **kw):
        erhalten.update(kw)
        return NerBilanz()

    monkeypatch.setattr(ablauf, "ner_ausfuehren", fake)
    r = runner.invoke(cli.app, ["ner", "--labels", "person, aktenzeichen=file number", "--schwelle", "0.3"],
                      obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert erhalten["labels"] == labels_parsen("person, aktenzeichen=file number")
    assert erhalten["schwelle"] == 0.3


def test_suche_cli_volltext_und_embed(session, cli_settings):
    from tests.embed.test_index import chunks_anlegen

    chunks_anlegen(session, ["Die Rechnung liegt vor."])
    ergebnis = runner.invoke(cli.app, ["suche", "--volltext", "Rechnungen"], obj=cli_settings)
    assert ergebnis.exit_code == 0, ergebnis.output
    assert "s1.txt" in ergebnis.output


def test_suche_cli_ohne_embeddings(session, cli_settings):
    ergebnis = runner.invoke(cli.app, ["suche", "etwas"], obj=cli_settings)
    assert ergebnis.exit_code == 1
    assert "vfm embed" in ergebnis.output


def test_analyse_cli(session, cli_settings, monkeypatch):
    import app.analyse.ablauf as ablauf
    from app.enums import AnalyseArt

    aufrufe = []
    flags = []

    def fake(session, s, arten, dokument_id=None, bei_dokument=None, soll_abbrechen=None, nur_fehlende=True):
        aufrufe.append((arten, dokument_id))
        flags.append(nur_fehlende)
        return ablauf.AnalyseBilanz(dokumente=2, erzeugt=3, fehler=1, uebersprungen=0)

    monkeypatch.setattr(ablauf, "analyse_ausfuehren", fake)
    r = runner.invoke(cli.app, ["analyse", "--art", "klassifikation", "--dokument", "7"], obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert aufrufe == [({AnalyseArt.KLASSIFIKATION}, 7)]
    assert "erzeugt: 3" in r.output and "Fehler: 1" in r.output
    r = runner.invoke(cli.app, ["analyse"], obj=cli_settings)
    assert aufrufe[-1] == (set(AnalyseArt), None)
    assert runner.invoke(cli.app, ["analyse", "--art", "quark"], obj=cli_settings).exit_code == 2
    runner.invoke(cli.app, ["analyse", "--alle-neu"], obj=cli_settings)
    assert flags == [True, True, False]


def _pipeline_stufen(monkeypatch, embed_fehler=False):
    import app.analyse.ablauf as analyse
    import app.embed.index as index
    import app.ingest.ablauf as ingest
    import app.ner.ablauf as ner
    from app.ingest.ablauf import IngestBilanz

    aufrufe = []
    monkeypatch.setattr(ingest, "ingest_clients", lambda s: None)
    monkeypatch.setattr(ingest, "ingest_ordner", lambda *a, **k: aufrufe.append("ingest") or IngestBilanz(neu=2, bekannt=1))
    monkeypatch.setattr(ner, "ner_ausfuehren", lambda *a, **k: aufrufe.append("ner") or ner.NerBilanz(dokumente=3, entitaeten=9))

    def fake_embed(*a, **k):
        aufrufe.append("embed")
        if embed_fehler:
            raise ProviderFehler("embed", "http://embed/v1", "embed-m", "nicht erreichbar")
        return index.EmbedBilanz(neu=5, vorhanden=0, dimension=3)

    monkeypatch.setattr(index, "embed_ausfuehren", fake_embed)
    monkeypatch.setattr(analyse, "analyse_ausfuehren", lambda *a, **k: aufrufe.append("analyse") or analyse.AnalyseBilanz(dokumente=3, erzeugt=6))
    return aufrufe


def test_pipeline_alle_stufen(cli_settings, tmp_path, monkeypatch):
    aufrufe = _pipeline_stufen(monkeypatch)
    r = runner.invoke(cli.app, ["pipeline", str(tmp_path)], obj=cli_settings)
    assert r.exit_code == 0, r.output
    assert aufrufe == ["ingest", "ner", "embed", "analyse"]
    assert "neu: 2" in r.output and "Entitäten: 9" in r.output and "Embeddings: 5" in r.output and "erzeugt: 6" in r.output


def test_pipeline_providerfehler_behaelt_fruehere_stufen(cli_settings, tmp_path, monkeypatch):
    aufrufe = _pipeline_stufen(monkeypatch, embed_fehler=True)
    r = runner.invoke(cli.app, ["pipeline", str(tmp_path)], obj=cli_settings)
    assert r.exit_code == 2
    assert aufrufe == ["ingest", "ner", "embed"]
    assert "neu: 2" in r.output and "Entitäten: 9" in r.output  # frühere Stufen sind gemeldet
    assert "nicht erreichbar" in r.output and "Traceback" not in r.output
    assert "Stufe 3/4 (Embeddings) abgebrochen" in r.output
    assert "vfm embed" in r.output and "vfm analyse" in r.output


def test_pipeline_pfad_fehlt(cli_settings, tmp_path):
    r = runner.invoke(cli.app, ["pipeline", str(tmp_path / "nix")], obj=cli_settings)
    assert r.exit_code == 1


@respx.mock
def test_frage_bei_rerank_fehler_exit_2(cli_settings, session, monkeypatch):
    from app.models import Embedding
    from tests.embed.test_index import chunks_anlegen

    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    chunk = chunks_anlegen(session, ["Inhalt"])[0]
    session.add(Embedding(chunk_id=chunk.id, modell="embed-m", vektor=[0.1, 0.2, 0.3]))
    session.commit()
    respx.post("http://embed/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]})
    )
    respx.post("http://rr/v1/rerank").mock(return_value=httpx.Response(500, text="model requires more system memory"))
    cli_settings.rerank_backend = "api"
    cli_settings.rerank_base_url = "http://rr/v1"
    cli_settings.rerank_model = "rr-m"
    r = runner.invoke(cli.app, ["frage", "Was?"], obj=cli_settings)
    assert r.exit_code == 2
    assert "model requires more system memory" in r.output
    assert "Traceback" not in r.output


def test_status_aus_fremdem_arbeitsverzeichnis(tmp_path, monkeypatch, engine):
    from tests.conftest import TEST_DATABASE_URL

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    r = runner.invoke(cli.app, ["status"])
    assert r.exit_code == 0, r.output
    assert "pdf" in r.output


def test_sql_befehl_ohne_readonly_url(cli_settings):
    cli_settings.sql_readonly_url = None
    r = runner.invoke(cli.app, ["sql", "SELECT 1"], obj=cli_settings)
    assert r.exit_code == 1
    assert "SQL_READONLY_URL ist nicht gesetzt" in r.output and "Traceback" not in r.output


def test_ner_cli_alle_neu(session, cli_settings, monkeypatch):
    import app.ner.ablauf as ner

    flags = []

    def fake(session, s, methoden, nur_fehlende=True, **k):
        flags.append(nur_fehlende)
        return ner.NerBilanz(dokumente=1)

    monkeypatch.setattr(ner, "ner_ausfuehren", fake)
    assert runner.invoke(cli.app, ["ner"], obj=cli_settings).exit_code == 0
    assert runner.invoke(cli.app, ["ner", "--alle-neu"], obj=cli_settings).exit_code == 0
    assert flags == [True, False]
