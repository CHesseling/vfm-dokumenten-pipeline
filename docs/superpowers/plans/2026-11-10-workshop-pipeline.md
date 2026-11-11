# Workshop-Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Gerichtstermine-Auswerter zu einer generischen Rechercheakten-Pipeline umbauen
(Ingest/OCR → NER → Embeddings/RAG → LLM-Analyse → GUI/CLI/API), die mit Ollama und Cortecs läuft.

**Architecture:** FastAPI + SQLModel + Postgres/pgvector bleiben. Jeder Pipeline-Schritt ist ein
eigenes Paket unter `app/` mit reinen Funktionen, die Session und Clients übergeben bekommen;
CLI (`vfm`, Typer), GUI (Jinja) und JSON-API rufen dieselben Funktionen auf. Modell-Zugriff läuft
über `app/providers/` (OpenAI-kompatibles HTTP + lokale Backends für Rerank/Whisper).

**Tech Stack:** Python 3.12, uv, FastAPI, SQLModel/Alembic, pgvector, httpx, Typer + rich,
pypdfium2, docling, faster-whisper, gliner2 (Fallback gliner), sentence-transformers,
schwifty, phonenumbers, dateparser, pillow + pillow-heif, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-11-10-workshop-pipeline-design.md`

## Global Constraints

- Code, Bezeichner, UI-Texte und Fehlermeldungen auf Deutsch (Umlaute in UI-Texten ja, in Bezeichnern ae/oe/ue wie bisher im Repo).
- Jede `app/<pkg>/<datei>.py` hat `tests/<pkg>/test_<datei>.py` (1:1-Spiegelung, AGENTS.md).
- Tests gegen echte Postgres+pgvector: `TEST_DATABASE_URL`, Default `postgresql+psycopg://postgres:postgres@localhost:5433/vfm_test`. Start: `docker run -d --name vfm-testdb -p 5433:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=vfm_test pgvector/pgvector:pg16`.
- HTTP-Modellaufrufe in Tests mit respx mocken; lokale Modelle (GliNER, Whisper, Docling, CrossEncoder) hinter Funktionen/Klassen, die in Tests per monkeypatch ersetzt werden. Echte Modelltests: `@pytest.mark.modelle`, standardmäßig per `addopts = "-m 'not modelle'"` ausgeschlossen.
- Lokale Modelle werden erst bei Erstbenutzung geladen (Modul-Cache), nie beim Import.
- Rollen: `chat`, `vision`, `embed`, `rerank`, `transcribe`. Provider-Profile: `ollama`, `cortecs`.
- Ollama aus dem Container: `http://host.docker.internal:11434/v1`. Cortecs: `https://api.cortecs.ai/v1` (in Task 0 verifizieren).
- Kein Video, kein MCP, kein Classifier, kein OpenSanctions.
- Material liegt nie im Repo; Ordner `material/` und `data/` sind gitignored.
- Lange Läufe in der GUI: Hintergrund-Thread + `app/progress.py` + Polling alle 2 s (bestehendes Muster). Einzelne LLM-Calls (RAG-Antwort, Check) synchron.
- Kein Vektor-Index; exakte Suche mit `cosine_distance`.
- Commits enden mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Defekte/unbekannte Datei** (kaputtes oder passwortgeschütztes PDF, .docx, .zip) → Dokument wird gespeichert, `Lauf` mit `status=fehler` und lesbarer Meldung, der Ingest macht mit der nächsten Datei weiter. Test in Task 12.
2. **Dieselbe Datei mehrfach** (zweimal im Ordner, und zusätzlich als Mail-Anhang) → genau ein `Dokument` (SHA-256), keine doppelten Extraktionen. Tests in Task 8 und 10.
3. **Provider nicht erreichbar / Modell fehlt** (Ollama aus, Tippfehler im Modellnamen, falscher Key) → CLI und GUI zeigen deutsche Meldung mit Rolle, URL und Modell statt Traceback; `vfm check` markiert die Rolle rot. Tests in Task 6.
4. **Leerer Text** (Foto ohne Schrift, stilles Audio, Scan ohne OCR-Ergebnis) → Extraktion mit leerem Text gespeichert, keine Chunks, NER/Embed/Analyse überspringen ohne Absturz. Tests in Task 8 und 18.
5. **Embedding-Modell gewechselt** → Suche nutzt nur Vektoren des aktuell konfigurierten Modells; gibt es keine, Meldung „Für Modell X gibt es noch keine Embeddings – erst `vfm embed` ausführen“. Test in Task 19.

---

## Dateistruktur (Ziel)

```
app/
  config.py                Settings + lade_settings(provider)
  db.py                    (bleibt)
  enums.py                 DokumentTyp, ExtraktionsMethode, NerMethode, AnalyseArt, LaufStatus
  progress.py              (bleibt, Felder klassifikation/verfahren entfernt)
  logging_config.py        (bleibt)
  main.py                  create_app, Router
  cli.py                   Typer-App "vfm"
  providers/
    llm_client.py          verschoben aus extraction/, + chat_text, Bild-MIME, extra_body
    embeddings.py          verschoben aus rag/, + embed_viele
    rerank.py              ApiReranker (aus rag/), LokalerReranker, KeinReranker
    transcribe.py          LokalerTranskribierer, ApiTranskribierer
    factory.py             Clients je Rolle aus Settings
    check.py               pruefe_rollen
  models/
    dokument.py            Dokument, TextExtraktion, Chunk, Embedding
    auswertung.py          Entitaet, Analyse, Lauf
  ingest/
    dateitypen.py, speichern.py, chunking.py, pdf.py, eml.py, eml_parse.py (verschoben),
    audio.py, bild.py, text.py, ablauf.py (Orchestrierung + Ordner)
  ner/      muster.py, gliner.py, llm_ner.py, ablauf.py
  embed/    index.py, suche.py, volltext.py, rag.py
  analyse/  kategorien.py, ablauf.py (zusammenfassen, klassifizieren, bild_beschreiben)
  sql/      abfrage.py, beispiele.py
  api/      routes.py
  web/      routes_dokumente.py, routes_upload.py, routes_entitaeten.py, routes_suche.py,
            routes_sql.py, routes_status.py, templates/
profile/    ollama.env, cortecs.env
config/     kategorien.yaml
scripts/    modelle_laden.py, fixtures_erzeugen.py, image_bauen.sh, usb_paket_bauen.sh,
            einspielen.sh, einspielen.ps1
docs/workshop/  tag1.md, tag2.md, tag3.md
```

---

### Task 0: Machbarkeits-Spike (wegwerfbar)

Kein Produktcode, keine Tests. Ergebnis ist eine Notiz, die Modellwahl und Fallbacks festlegt.

**Files:**
- Create: `docs/superpowers/spike-ergebnisse.md`
- Scratch (nicht committen): `spike/` (in `.gitignore` aufnehmen)

- [ ] **Step 1:** In einem venv (`uv venv spike/.venv`) `gliner2`, `gliner`, `docling`, `faster-whisper`, `sentence-transformers` installieren.
- [ ] **Step 2: GliNER2 Deutsch.** Fünf deutsche Sätze mit Personen, Firmen, Orten, Beträgen, Daten durch `fastino/gliner2-base-v1` und `urchade/gliner_multi-v2.1` schicken, jeweils mit deutschen und englischen Labelnamen. Treffer zählen. Entscheidung: Paket, Modell, Labelsprache.
- [ ] **Step 3: Docling offline.** `docling-tools models download` in ein Verzeichnis, dann ein Scan-PDF mit `HF_HUB_OFFLINE=1`, `artifacts_path` und EasyOCR `lang=["de"]` konvertieren. Messen: Dauer/Seite (CPU), Größe des Modellordners. Prüfen, ob EasyOCR-Gewichte zusätzlich geladen werden müssen.
- [ ] **Step 4: Whisper.** `faster-whisper` `small`, `int8`, CPU, eine deutsche 30-s-Sprachnachricht (.opus und .m4a). Dauer und Qualität notieren.
- [ ] **Step 5: Reranker.** Zwei kleine mehrsprachige Cross-Encoder (z. B. `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, `jinaai/jina-reranker-v2-base-multilingual`) mit einer deutschen Frage und 10 Absätzen. Entscheidung nach Ranking-Plausibilität und Größe.
- [ ] **Step 6: Ollama.** Gegen `http://localhost:11434/v1`: `response_format` `json_schema` mit `qwen3.5:4b`; Bild als `data:image/jpeg;base64` an `qwen3.5:4b` und `qwen3-vl:8b`; `/v1/embeddings` mit `bge-m3` bzw. `qwen3-embedding:0.6b` (vorher `ollama pull`), Dimension notieren; wie Thinking abgeschaltet wird (`reasoning_effort: "none"` vs. `think: false` im Body) – Ergebnis wird der Wert von `CHAT_EXTRA_BODY` im Profil.
- [ ] **Step 7: Cortecs.** Mit Key (vom Nutzer erfragen): `GET /models`, dann je ein Aufruf `chat/completions` (JSON-Schema), Bild-Input, `embeddings`, `audio/transcriptions`, `rerank`. Tabelle: Endpunkt → geht/geht nicht, Modellnamen.
- [ ] **Step 8: Image-Größe.** Grob: Summe venv (`du -sh spike/.venv`) + Modellordner. Notieren.
- [ ] **Step 9:** Ergebnisse und Entscheidungen in `docs/superpowers/spike-ergebnisse.md` schreiben (Tabelle je Rolle: Ollama-Modell, Cortecs-Modell oder `local`-Fallback). Abweichungen von den Defaults in diesem Plan dort festhalten; spätere Tasks nehmen die Werte von dort.
- [ ] **Step 10: Commit** `docs: Spike-Ergebnisse` (nur die .md und `.gitignore`).

---

### Task 1: Aufräumen

**Files:**
- Delete: `app/graph/`, `app/imap/`, `app/scheduler.py`, `app/search/`, `app/watchfolder/`, `app/rag/index.py`, `app/rag/search.py`, `app/rag/answer.py`, `app/extraction/{classify,extract,prefilter,chunking,vollstaendigkeit,schemas}.py`, `app/pipeline/{upsert,aktenzeichen,ingest,mail_store,dokumente}.py`, `app/models/{email,verfahren}.py`, alle `app/web/routes_*.py`, alle Templates außer `base.html`, `alembic/versions/*`, `scripts/*`, zugehörige Tests, `tests/fixtures/*` (Gerichtsmails), `docs/superpowers/plans/2026-09-21-*`, `docs/superpowers/specs/2026-09-21-*`. Behalten: `docs/superpowers/plans/ndr_UI.md` und `NDR_pos_digital.png` (Design-Referenz). `tmp/` und `dist/` sind gitignored und bleiben lokal unangetastet (Löschen nur nach Rückfrage).
- Move (git mv): `app/extraction/llm_client.py` → `app/providers/llm_client.py`; `app/rag/embeddings.py` → `app/providers/embeddings.py`; `app/rag/rerank.py` → `app/providers/rerank.py`; `app/extraction/pdf_render.py` → `app/ingest/pdf_render.py`; `app/pipeline/eml_parse.py` → `app/ingest/eml_parse.py`; Tests entsprechend.
- Modify: `app/main.py`, `app/progress.py`, `pyproject.toml`, `app/models/__init__.py`, `tests/conftest.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI` mit `GET /gesundheit` → `{"status": "ok"}`.

- [ ] **Step 1:** Löschen/Verschieben wie oben. In `pyproject.toml`: name `vfm-pipeline`, description „Workshop-Pipeline für Dokumenten-Analyse mit LLMs“, `msal` und `apscheduler` entfernen; `[tool.pytest.ini_options]` um `markers = ["modelle: braucht echte lokale Modelle"]` und `addopts = "-m 'not modelle'"` ergänzen. `progress.py`: Felder `klassifikation`, `verfahren` und die gleichnamigen Parameter von `abschliessen` entfernen. `tests/conftest.py`: Default-DB-Name `vfm_test`.
- [ ] **Step 2: Test schreiben** `tests/test_main.py::test_gesundheit` – `TestClient(create_app()).get("/gesundheit")` → 200, `{"status": "ok"}`. `create_app` darf keinen Scheduler mehr starten und keine Settings beim Import verlangen.
- [ ] **Step 3:** `app/main.py` auf Lifespan ohne Scheduler, nur `/static` und `/gesundheit` reduzieren (Router kommen in späteren Tasks dazu).
- [ ] **Step 4:** `uv sync && uv run pytest` → verbleibende Tests (llm_client, embeddings, rerank, pdf_render, eml_parse, progress, main) grün; Imports an neue Pfade angepasst.
- [ ] **Step 5: Commit** `chore: Gerichtstermine-Code entfernen, generische Teile verschieben`.

---

### Task 2: Settings und Provider-Profile

**Files:**
- Modify: `app/config.py`
- Create: `profile/ollama.env`, `profile/cortecs.env`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `class Settings(BaseSettings)` mit Feldern (Default in Klammern):
    `database_url`, `sql_readonly_url: str | None (None)`, `daten_pfad ("/data/dateien")`, `material_pfad ("/material")`, `log_level ("INFO")`, `provider ("ollama")`, `api_token: str | None`, `cortecs_api_key: str | None`,
    `chat_base_url`, `chat_model`, `chat_api_key: str | None`, `chat_timeout_sekunden (600.0)`, `chat_structured_outputs (True)`, `chat_extra_body: dict ({})`,
    `vision_base_url: str | None`, `vision_model: str | None`, `vision_api_key: str | None`,
    `embed_base_url`, `embed_model`, `embed_api_key: str | None`, `embed_batch (32)`,
    `rerank_backend: Literal["local","api","none"] ("local")`, `rerank_model`, `rerank_base_url: str | None`, `rerank_api_key: str | None`,
    `transcribe_backend: Literal["local","api"] ("local")`, `transcribe_model ("small")`, `transcribe_base_url: str | None`, `transcribe_api_key: str | None`,
    `gliner_model`, `docling_artifacts_pfad ("/models/docling")`,
    `chunk_zeichen (1500)`, `chunk_ueberlappung (200)`, `rag_top_n (50)`, `rag_top_k (8)`,
    `kategorien_pfad ("config/kategorien.yaml")`.
    Validator: leere Strings → None für alle optionalen Felder (bestehendes Muster aus `_leere_zeichenkette_als_none`).
  - `lade_settings(provider: str | None = None) -> Settings` – liest `.env`, bestimmt Provider (Argument > `PROVIDER` aus Env/.env > "ollama"), lädt dann `env_file=(f"profile/{provider}.env", ".env")` (spätere Datei gewinnt). Unbekannter Provider → `ValueError("Unbekannter Provider 'x' – erlaubt: ollama, cortecs")`.
  - `Settings.api_key_fuer(rolle: str) -> str | None` – Rollen-Key, sonst bei `provider == "cortecs"` `cortecs_api_key`, sonst None.
  - `Settings.vision_effektiv() -> tuple[str, str, str | None]` – (base_url, model, key), fällt auf chat_* zurück.
  - `get_settings()` bleibt (lru_cache um `lade_settings()`).

- [ ] **Step 1: Tests schreiben** (`tmp_path` + `monkeypatch.chdir`, Profil-Dateien dort anlegen):
  - `test_profil_ollama_ist_default` – ohne PROVIDER → `s.provider == "ollama"`, `s.chat_base_url` aus `profile/ollama.env`.
  - `test_provider_argument_schlaegt_env` – `.env` mit `PROVIDER=ollama`, `lade_settings("cortecs").chat_base_url == "https://api.cortecs.ai/v1"`.
  - `test_env_ueberschreibt_profil` – `.env` mit `CHAT_MODEL=x` → `s.chat_model == "x"`.
  - `test_cortecs_key_als_fallback` – `CORTECS_API_KEY=k`, provider cortecs → `s.api_key_fuer("embed") == "k"`; provider ollama → `None`.
  - `test_vision_faellt_auf_chat_zurueck`.
  - `test_unbekannter_provider` → `ValueError` mit „erlaubt: ollama, cortecs“.
  - `test_leere_optionale_felder_sind_none` – `RERANK_BASE_URL=` → None.
- [ ] **Step 2:** `uv run pytest tests/test_config.py -v` → FAIL.
- [ ] **Step 3:** Implementieren. Profile mit Werten aus Task 0; Platzhalter, falls Spike noch offen:
  `profile/ollama.env`: `CHAT_BASE_URL=http://host.docker.internal:11434/v1`, `CHAT_MODEL=qwen3.5:4b`, `VISION_MODEL=qwen3.5:4b`, `EMBED_BASE_URL=http://host.docker.internal:11434/v1`, `EMBED_MODEL=bge-m3`, `RERANK_BACKEND=local`, `RERANK_MODEL=<aus Spike>`, `TRANSCRIBE_BACKEND=local`, `CHAT_EXTRA_BODY=<aus Spike>`.
  `profile/cortecs.env`: Base-URLs `https://api.cortecs.ai/v1`, Modelle und Backends laut Spike-Tabelle, Kommentar je Rolle, was lokal bleibt.
  `.env.example`: `PROVIDER=ollama`, `DATABASE_URL=postgresql+psycopg://vfm:vfm@db:5432/vfm`, `SQL_READONLY_URL=postgresql+psycopg://vfm_leser:vfm_leser@db:5432/vfm`, `CORTECS_API_KEY=`, `API_TOKEN=`, Kommentar „Einzelwerte aus profile/*.env hier überschreiben“.
- [ ] **Step 4:** Tests → PASS.
- [ ] **Step 5: Commit** `feat: Settings je Rolle mit Provider-Profilen`.

---

### Task 3: LLM-Client erweitern

**Files:**
- Modify: `app/providers/llm_client.py`
- Test: `tests/providers/test_llm_client.py`

**Interfaces:**
- Produces (zusätzlich zu bestehendem `chat_json(messages, schema) -> T`):
  - `LLMClient.__init__(..., extra_body: dict | None = None)` – wird in jeden Request-Body gemischt.
  - `LLMClient.chat_text(messages: list[dict]) -> str` – ohne `response_format`, gibt `content.strip()` zurück; entfernt `<think>…</think>`-Blöcke.
  - `bild_nachricht(text: str, bilder: list[tuple[bytes, str]]) -> dict` (Modulfunktion) – User-Message mit `image_url`-Parts, `(inhalt, mime)` je Bild.
  - `chat_json_with_image` bekommt `bilder: list[tuple[bytes, str]]` statt `images_png` (nutzt `bild_nachricht`).
  - Korrektur-Prompt der Reparatur-Runde neutral (keine Gerichtsbegriffe).
  - `class ProviderFehler(Exception)` mit Attributen `rolle`, `base_url`, `modell`, `meldung`; `__str__` → `"{rolle}: {meldung} ({modell} @ {base_url})"`. LLMClient bekommt Konstruktor-Parameter `rolle: str = "chat"` und wandelt `httpx.ConnectError` → `ProviderFehler(meldung="nicht erreichbar")`, HTTP 404 → `"Modell nicht gefunden"`, 401/403 → `"API-Key fehlt oder ist ungültig"`.

- [ ] **Step 1: Tests** (respx):
  - `test_chat_text_ohne_response_format` – Request-JSON hat keinen Key `response_format`, Rückgabe `"Hallo"` bei content `"  Hallo \n"`.
  - `test_chat_text_entfernt_think_block` – content `"<think>xx</think>Antwort"` → `"Antwort"`.
  - `test_extra_body_wird_mitgeschickt` – `extra_body={"reasoning_effort": "none"}` → im Request-JSON.
  - `test_bild_mit_mime` – `bild_nachricht("t", [(b"x", "image/jpeg")])["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")`.
  - `test_verbindungsfehler_wird_providerfehler` – respx `side_effect=httpx.ConnectError` → `ProviderFehler`, `"nicht erreichbar" in str(e)`, `e.rolle == "chat"`.
  - `test_404_wird_modell_nicht_gefunden`, `test_401_wird_key_fehler`.
- [ ] **Step 2:** FAIL prüfen. **Step 3:** Implementieren (bestehende Retry-/Timeout-Logik unverändert; Mapping in ProviderFehler nach den Retries). **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: LLMClient mit Freitext, Bild-MIME und lesbaren Providerfehlern`.

---

### Task 4: Embeddings, Reranker, Transkription, Factory

**Files:**
- Modify: `app/providers/embeddings.py`, `app/providers/rerank.py`
- Create: `app/providers/transcribe.py`, `app/providers/factory.py`
- Test: `tests/providers/test_embeddings.py`, `test_rerank.py`, `test_transcribe.py`, `test_factory.py`

**Interfaces:**
- Produces:
  - `EmbeddingClient(base_url, model, api_key=None, timeout=60.0, batch=32, rolle="embed")`; `embed(text) -> list[float]`; `embed_viele(texte: list[str]) -> list[list[float]]` (Batches à `batch`, Reihenfolge nach `data[i].index`). Fehler → `ProviderFehler` wie Task 3.
  - `class Reranker(Protocol): def rerank(self, frage: str, texte: list[str]) -> list[tuple[int, float]]` (absteigend nach Score).
  - `ApiReranker(base_url, model, api_key, timeout)` (bisheriger `RerankClient`, umbenannt), `LokalerReranker(model: str)` (sentence-transformers `CrossEncoder`, lazy geladen beim ersten `rerank`, `predict` auf Paare), `KeinReranker()` → `[(i, 0.0) for i in range(len(texte))]`.
  - `class Transkribierer(Protocol): def transkribieren(self, inhalt: bytes, dateiname: str) -> str`.
  - `LokalerTranskribierer(model: str)` – faster-whisper `WhisperModel(model, device="cpu", compute_type="int8")` lazy; schreibt Bytes in Tempdatei mit Original-Suffix; `language="de"`, `vad_filter=True`; Segmente mit Leerzeichen verbunden.
  - `ApiTranskribierer(base_url, model, api_key)` – `POST /audio/transcriptions` multipart (`file`, `model`, `language=de`), Rückgabe `json["text"]`.
  - factory: `chat_client(s: Settings) -> LLMClient`, `vision_client(s) -> LLMClient` (rolle="vision"), `embedding_client(s) -> EmbeddingClient`, `reranker(s) -> Reranker`, `transkribierer(s) -> Transkribierer`. `rerank_backend="api"` ohne `rerank_base_url` → `ValueError("RERANK_BASE_URL fehlt für RERANK_BACKEND=api")`.

- [ ] **Step 1: Tests:**
  - `test_embed_viele_batcht` – 5 Texte, batch=2 → 3 Requests, Ergebnis-Reihenfolge stimmt auch wenn Antwort `index` umgekehrt liefert.
  - `test_kein_reranker_behaelt_reihenfolge` → `[(0,0.0),(1,0.0)]`.
  - `test_lokaler_reranker_sortiert` – `monkeypatch` CrossEncoder-Ladefunktion mit Fake, dessen `predict` `[0.1, 0.9]` liefert → `[(1, 0.9), (0, 0.1)]`; Ladefunktion wird erst bei `rerank` aufgerufen (Zähler 0 nach Konstruktor).
  - `test_api_transkribierer_sendet_multipart` (respx, prüft `language=de` im Body).
  - `test_lokaler_transkribierer_verbindet_segmente` (Fake-Modell).
  - `test_factory_rerank_backends` – je Backend richtige Klasse; api ohne URL → ValueError.
  - `test_factory_vision_nutzt_chat_fallback`.
  - `@pytest.mark.modelle test_lokaler_reranker_echt` – deutsche Frage, relevanter Absatz landet auf Platz 1.
- [ ] **Step 2:** FAIL. **Step 3:** Implementieren; Abhängigkeiten `faster-whisper`, `sentence-transformers` und torch-CPU in `pyproject.toml` (uv-Index `pytorch-cpu` = `https://download.pytorch.org/whl/cpu`, `[tool.uv.sources] torch = [{ index = "pytorch-cpu", marker = "sys_platform == 'linux' and platform_machine == 'x86_64'" }]`). **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: Embedding-Batching, Reranker- und Transkriptions-Backends, Client-Factory`.

---

### Task 5: Datenmodell und Basis-Migration

**Files:**
- Create: `app/models/dokument.py`, `app/models/auswertung.py`, `alembic/versions/0001_basis.py`
- Modify: `app/enums.py`, `app/models/__init__.py`, `tests/conftest.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - Enums (str-Enums): `DokumentTyp` = pdf, eml, audio, bild, text, sonstig; `ExtraktionsMethode` = schnell, docling, vision, whisper, eml, text; `NerMethode` = gliner, muster, llm; `AnalyseArt` = zusammenfassung, klassifikation, bildbeschreibung; `LaufStatus` = erfolg, fehler, uebersprungen.
  - `Dokument`: id, sha256 (unique, index), dateiname, typ: DokumentTyp, mime: str, groesse: int, parent_id: int | None (FK dokument.id), metadaten: dict (JSON), erstellt_am. Property `dateipfad(daten_pfad: str) -> Path` = `Path(daten_pfad)/sha256[:2]/sha256`.
  - `TextExtraktion`: id, dokument_id (FK), methode: ExtraktionsMethode, text, modell: str | None, dauer_ms: int, ist_aktiv: bool, erstellt_am. Unique (dokument_id, methode).
  - `Chunk`: id, textextraktion_id (FK, ON DELETE CASCADE), position, start, ende, text, `tsv` = `Column(TSVECTOR, Computed("to_tsvector('german', text)", persisted=True))`, GIN-Index auf tsv.
  - `Embedding`: id, chunk_id (FK, CASCADE), modell (index), vektor = `Column(Vector())` (ohne Dimension), erstellt_am. Unique (chunk_id, modell).
  - `Entitaet`: id, textextraktion_id (FK, CASCADE), methode: NerMethode, label, text, normalisiert: str | None, start, ende, score: float | None.
  - `Analyse`: id, dokument_id (FK), art: AnalyseArt, modell, ergebnis: dict (JSON), erstellt_am. Unique (dokument_id, art) – neue Analyse ersetzt alte.
  - `Lauf`: id, schritt (str: ingest/ner/embed/analyse), dokument_id: int | None, provider, modell: str | None, dauer_ms, status: LaufStatus, fehler: str | None, roh_output: dict | None, erstellt_am.
  - Migration `0001_basis`: `CREATE EXTENSION IF NOT EXISTS vector`, alle Tabellen, danach Read-only-Rolle: `DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='vfm_leser') THEN CREATE ROLE vfm_leser LOGIN PASSWORD 'vfm_leser'; END IF; END $$;`, `GRANT CONNECT ON DATABASE <current_database()>`, `GRANT USAGE ON SCHEMA public`, `GRANT SELECT ON ALL TABLES IN SCHEMA public`, `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO vfm_leser`, `ALTER ROLE vfm_leser SET statement_timeout = '10s'`.

- [ ] **Step 1: Tests:**
  - `test_embedding_verschiedene_dimensionen` – zwei Embeddings mit Länge 3 (modell "a") und 5 (modell "b") am selben Chunk speichern und zurücklesen.
  - `test_chunk_tsvector_wird_berechnet` – nach Insert `SELECT tsv @@ to_tsquery('german','Rechnungen')` für Chunk-Text „Die Rechnung kam“ → True.
  - `test_sha256_unique` – zweites Dokument mit gleichem sha → `IntegrityError`.
  - `test_extraktion_loeschen_kaskadiert` – Chunk, Embedding, Entitaet weg.
- [ ] **Step 2:** FAIL. **Step 3:** Implementieren; Migration handgeschrieben (nicht autogenerate), `import sqlmodel` und `pgvector.sqlalchemy` drin. **Step 4:** PASS; zusätzlich `alembic upgrade head` gegen eine leere DB (Test-Container, andere DB `vfm_mig`) läuft durch.
- [ ] **Step 5: Commit** `feat: Datenmodell für Dokumente, Extraktionen, Chunks, Embeddings, Entitäten, Analysen`.

---

### Task 6: CLI-Gerüst, `vfm check`, `vfm status`

**Files:**
- Create: `app/cli.py`, `app/providers/check.py`
- Modify: `pyproject.toml` (`[project.scripts] vfm = "app.cli:app"`, deps `typer`, `rich`)
- Test: `tests/test_cli.py`, `tests/providers/test_check.py`

**Interfaces:**
- Produces:
  - `@dataclass RollenCheck(rolle: str, backend: str, modell: str, ok: bool, detail: str)`.
  - `pruefe_rollen(s: Settings) -> list[RollenCheck]` – chat: `chat_text` „Antworte nur mit OK.“; vision: Mini-PNG (1×1 weiß) + „Welche Farbe?“; embed: `embed("Test")`, detail `"Dimension {n}"`; rerank: 2 Texte; transcribe local: nur Prüfung, dass Modellordner existiert (kein Laden), api: `GET /models` erreichbar. Jede Rolle fängt `ProviderFehler`/`Exception` einzeln → `ok=False`, `detail=str(e)`.
  - `app/cli.py`: `app = typer.Typer()`, globale Option `--provider/-p` (Callback setzt `ctx.obj = lade_settings(provider)`); Hilfsfunktion `session_aus(s) -> Session`. Befehle `check` (rich-Tabelle, Exit-Code 1 wenn eine Rolle `ok=False`) und `status` (Tabelle: Typ | Dokumente | mit aktivem Text | mit Entitäten | mit Embeddings (aktuelles Modell) | mit Analyse).
  - CLI-Konvention für alle späteren Befehle: `ProviderFehler` wird gefangen, rot ausgegeben, Exit-Code 2, kein Traceback.

- [ ] **Step 1: Tests** (typer `CliRunner`, respx, Settings per Fixture `cli_settings` ins Typer-Objekt injiziert):
  - `test_check_alles_ok` → Exit 0, Ausgabe enthält „Dimension 3“.
  - `test_check_ollama_aus` – chat ConnectError → Exit 1, Ausgabe enthält „chat“ und „nicht erreichbar“, kein „Traceback“.
  - `test_status_leer` → Exit 0, Tabelle mit 0-Werten.
  - `test_providerfehler_exitcode_2` – Dummy-Befehl in Test registriert, der ProviderFehler wirft → Exit 2.
- [ ] **Step 2:** FAIL. **Step 3:** Implementieren. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: vfm-CLI mit check und status`.

---

### Task 7: Docker, Compose, Modell-Vorladen

**Files:**
- Modify: `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`
- Create: `scripts/modelle_laden.py`, `.dockerignore`
- Test: manuell (Verifikationsschritte)

**Interfaces:**
- Produces: Image `vfm-pipeline:latest`, Modelle unter `/models` (`HF_HOME=/models/hf`, `docling_artifacts_pfad=/models/docling`, Whisper unter `/models/whisper`), `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` zur Laufzeit. `scripts/modelle_laden.py --ziel /models` lädt alle Modelle aus den Profil-Defaults (GliNER, Reranker, Whisper, Docling, EasyOCR de) – spätere Tasks ergänzen hier ihr Modell.

- [ ] **Step 1:** Dockerfile dreistufig: `modelle` (`FROM --platform=$BUILDPLATFORM python:3.12-slim`, eigenes venv nur mit `huggingface_hub`, `docling` und `faster-whisper`-Downloadern, führt `modelle_laden.py` aus), `builder` (uv sync `--no-dev --frozen`), Laufzeit (`python:3.12-slim` + `ffmpeg`, `libgl1`, `libglib2.0-0`; venv + `/models` kopieren; User `appuser` mit `APP_UID`). `.dockerignore`: `dist/ material/ data/ tmp/ spike/ .venv/ .git/ **/__pycache__`.
- [ ] **Step 2:** Compose: `db` (User/DB/Passwort `vfm`, Port nur intern + `5432:5432` auskommentiert), `app` (`image: vfm-pipeline:latest`, `build: .`, Port `8999:8000`, Volumes `daten:/data`, `./material:/material`, `extra_hosts host.docker.internal`), Service `ollama` mit `profiles: ["ollama"]` (`ollama/ollama`, Volume `ollama:/root/.ollama`, Port 11434). Meilisearch entfernen.
- [ ] **Step 3:** `entrypoint.sh`: `alembic upgrade head`, dann uvicorn. `vfm` liegt im venv auf PATH.
- [ ] **Step 4: Verifizieren:** `colima start` (bzw. Docker Desktop), `docker compose build && docker compose up -d`, `docker compose exec app vfm check` → chat/embed grün gegen Host-Ollama, rerank/transcribe grün. `docker image ls vfm-pipeline` Größe notieren.
- [ ] **Step 5: Commit** `build: Image mit vorgeladenen Modellen, Compose mit Ollama-Profil`.

---

### Task 8: Dokumente speichern, Typ-Erkennung, Chunking

**Files:**
- Create: `app/ingest/dateitypen.py`, `app/ingest/speichern.py`, `app/ingest/chunking.py`
- Test: `tests/ingest/test_dateitypen.py`, `test_speichern.py`, `test_chunking.py`

**Interfaces:**
- Produces:
  - `erkenne_typ(dateiname: str, inhalt: bytes) -> tuple[DokumentTyp, str]` (Typ, MIME). Magic Bytes vor Endung: `%PDF` → pdf; `.eml`/`message/rfc822` → eml; Endungen `.mp3 .m4a .ogg .opus .wav .aac .amr` → audio; `.jpg .jpeg .png .heic .heif .webp .tif .tiff` → bild; `.txt .md .csv` → text; sonst sonstig.
  - `chunken(text: str, zeichen: int, ueberlappung: int) -> list[tuple[int, int, str]]` – (start, ende, text); bricht an Absatz-, sonst Satz-, sonst Wortgrenze; leerer/whitespace-Text → `[]`.
  - `dokument_speichern(session, inhalt: bytes, dateiname: str, daten_pfad: str, parent_id: int | None = None, metadaten: dict | None = None) -> tuple[Dokument, bool]` – bool = neu angelegt; schreibt Datei nur wenn neu.
  - `extraktion_speichern(session, dokument: Dokument, methode: ExtraktionsMethode, text: str, modell: str | None, dauer_ms: int, s: Settings) -> TextExtraktion` – ersetzt vorhandene Extraktion gleicher Methode (Chunks/Entitäten/Embeddings kaskadieren weg); ruft danach `aktive_extraktion_waehlen`.
  - `aktive_extraktion_waehlen(session, dokument, s) -> TextExtraktion | None` – Priorität `docling, eml, text, whisper, schnell, vision`; erste mit `len(text.strip()) >= 20`, sonst die längste. Nur die aktive hat Chunks: Wechsel löscht Chunks der alten, erzeugt Chunks der neuen.
  - `aktiv_setzen(session, extraktion_id: int, s) -> None` – manueller Wechsel (GUI/CLI), gleiche Chunk-Logik.
  - `lesen_datei(dokument, daten_pfad) -> bytes`.

- [ ] **Step 1: Tests:**
  - `test_pdf_per_magic_bytes` – Datei `scan.bin` mit `%PDF-1.4…` → pdf.
  - `test_unbekannt_ist_sonstig` – `x.docx` → sonstig.
  - `test_chunken_ueberlappung` – 4000 Zeichen, 1500/200 → 3 Chunks, `chunks[1][0] == chunks[0][1] - 200 ± Wortgrenze` (≤ 50 Zeichen Toleranz), alle Texte = `text[start:ende]`.
  - `test_chunken_leer` → `[]`.
  - `test_gleiche_datei_einmal` – zweimal speichern → zweites `neu is False`, eine Zeile, Datei existiert unter `daten_pfad/ab/abcd…`.
  - `test_leere_extraktion_ohne_chunks` – Text `""` → Extraktion gespeichert, 0 Chunks, `ist_aktiv` True (einzige).
  - `test_aktive_extraktion_prioritaet` – schnell (500 Zeichen) + docling (480 Zeichen) → docling aktiv, Chunks hängen an docling.
  - `test_kurze_docling_verliert` – docling 5 Zeichen, schnell 500 → schnell aktiv.
- [ ] **Step 2:** FAIL. **Step 3:** Implementieren. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: Dokumente speichern mit Dedup, Typ-Erkennung, Chunking`.

---

### Task 9: PDF-Extraktion (schnell, docling, vision)

**Files:**
- Create: `app/ingest/pdf.py`
- Modify: `scripts/modelle_laden.py` (Docling + EasyOCR de)
- Test: `tests/ingest/test_pdf.py`

**Interfaces:**
- Consumes: `extract_pdf_text`, `render_pdf_pages_to_png` aus `app/ingest/pdf_render.py`; `LLMClient.chat_text`, `bild_nachricht`.
- Produces:
  - `pdf_schnell(inhalt: bytes) -> str`.
  - `pdf_docling(inhalt: bytes, artifacts_pfad: str) -> str` – `DocumentConverter` mit `PdfPipelineOptions(artifacts_path=…, do_ocr=True, ocr_options=EasyOcrOptions(lang=["de"]))`, Export `export_to_markdown()`. Converter modulweit gecacht (lazy).
  - `pdf_vision(inhalt: bytes, client: LLMClient, max_seiten: int = 20) -> str` – je Seite `chat_text` mit Prompt `VISION_TRANSKRIPTION_PROMPT` = „Gib den gesamten Text dieser Seite exakt wieder, Zeile für Zeile, ohne Kommentar. Gibt es keinen Text, antworte mit einer leeren Zeile.“; Seiten mit `\n\n--- Seite N ---\n\n` verbunden; mehr als `max_seiten` → nur die ersten, Hinweis am Ende.
  - Ungültiges PDF: `pdf_schnell` → `""` (bestehend); `pdf_docling`/`pdf_vision` werfen `ExtraktionsFehler(str)` (neu, in `app/ingest/pdf.py`).

- [ ] **Step 0:** Test-Helfer `tests/fixtures/pdf_bauen.py`: `mini_pdf(seiten: list[list[str]]) -> bytes` – baut ein gültiges PDF von Hand (Helvetica, eine Textzeile je Listeneintrag, korrekte xref-Offsets), keine neue Abhängigkeit; `scan_pdf(pdf: bytes) -> bytes` – rendert per `render_pdf_pages_to_png` und speichert die Bilder mit Pillow als PDF (keine Textebene). Wird auch von Task 12 und 24 genutzt.
- [ ] **Step 1: Tests:** `test_pdf_schnell_text` (`mini_pdf([["Hallo Welt"]])` → enthält „Hallo Welt“), `test_scan_pdf_hat_keinen_text` (`pdf_schnell(scan_pdf(...)).strip() == ""`), `test_pdf_vision_pro_seite` (respx: zwei Seiten → zwei Requests, Ergebnis enthält „--- Seite 2 ---“, Request enthält `data:image/png`), `test_pdf_docling_kaputt_wirft_extraktionsfehler` (monkeypatch Converter wirft), `@pytest.mark.modelle test_pdf_docling_scan` (Scan-Fixture, Text enthält erwartetes Wort).
- [ ] **Step 2:** FAIL. **Step 3:** Implementieren; `docling` in pyproject. **Step 4:** PASS.
- [ ] **Step 5: Commit** `feat: PDF-Extraktion schnell/docling/vision`.

---

### Task 10: E-Mails mit Anhängen

**Files:**
- Create: `app/ingest/eml.py`
- Test: `tests/ingest/test_eml.py`

**Interfaces:**
- Consumes: `parse_eml_message`, `extract_eml_attachments` (`app/ingest/eml_parse.py`, Graph-Form bleibt intern).
- Produces:
  - `eml_lesen(inhalt: bytes) -> EmlInhalt` (dataclass: `metadaten: dict` mit `absender`, `empfaenger: list[str]`, `betreff`, `datum` ISO, `text: str` = Kopfzeilen „Von/An/Datum/Betreff“ + Leerzeile + Body, `anhaenge: list[tuple[str, bytes]]`). Empfänger aus `To`/`Cc` ergänzen (eml_parse liefert sie bisher nicht – dort `toRecipients`/`ccRecipients` in Graph-Form ergänzen).

- [ ] **Step 1: Tests:** `test_eml_text_und_metadaten` (Mail per `email.message.EmailMessage` im Test gebaut: Von, An, Cc, Betreff, Body) → `metadaten["empfaenger"] == ["a@x.de", "b@x.de"]`, Text beginnt mit „Von: “; `test_eml_anhaenge` (PDF-Anhang → `anhaenge[0][0] == "rechnung.pdf"`); `test_html_tabelle_bleibt_zeilenweise` (bestehendes Verhalten).
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: E-Mails mit Empfängern und Anhängen lesen`.

---

### Task 11: Audio, Bilder, Text

**Files:**
- Create: `app/ingest/audio.py`, `app/ingest/bild.py`, `app/ingest/text.py`
- Modify: `pyproject.toml` (`pillow-heif`), `scripts/modelle_laden.py` (Whisper)
- Test: `tests/ingest/test_audio.py`, `test_bild.py`, `test_text.py`

**Interfaces:**
- Produces:
  - `audio_transkribieren(inhalt: bytes, dateiname: str, t: Transkribierer) -> str`.
  - `bild_metadaten(inhalt: bytes) -> dict` – Breite, Höhe, EXIF `DateTimeOriginal` (ISO), `Make`, `Model`, GPS als Dezimalgrad `{"lat":…, "lon":…}` falls vorhanden.
  - `bild_als_jpeg(inhalt: bytes, max_kante: int = 2048) -> bytes` – HEIC via pillow-heif, RGB, verkleinert.
  - `bild_ocr(inhalt: bytes, client: LLMClient) -> str` – `chat_text` mit `VISION_TRANSKRIPTION_PROMPT` (aus `pdf.py` importieren) und JPEG.
  - `text_lesen(inhalt: bytes) -> str` – UTF-8, Fallback cp1252.

- [ ] **Step 1: Tests:** `test_bild_metadaten_gps` (JPEG im Test mit Pillow + EXIF-GPS erzeugen → lat/lon ≈ 53.55/9.99), `test_bild_als_jpeg_verkleinert` (4000×100 PNG → max Kante 2048, beginnt mit `\xff\xd8`), `test_bild_ocr_schickt_jpeg` (respx), `test_text_cp1252` („Grüße“ in cp1252), `test_audio_delegiert` (Fake-Transkribierer).
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: Audio-Transkription, Bild-OCR mit EXIF, Textdateien`.

---

### Task 12: Ingest-Ablauf, Ordner, `vfm ingest`, `vfm text`

**Files:**
- Create: `app/ingest/ablauf.py`
- Modify: `app/cli.py`
- Test: `tests/ingest/test_ablauf.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 8–11, factory.
- Produces:
  - `@dataclass IngestClients(vision: LLMClient, transkribierer: Transkribierer)`; `ingest_clients(s) -> IngestClients` (lazy-freundlich, keine Modelle laden).
  - `ingest_datei(session, inhalt: bytes, dateiname: str, s: Settings, clients: IngestClients, methoden: set[str] | None = None, parent_id: int | None = None) -> Dokument` – speichert, wählt Methoden je Typ (pdf: Default `{"schnell"}` + automatisch `docling`, wenn schnell < 200 Zeichen; `methoden={"alle"}` → schnell, docling, vision; eml: eml + rekursiv Anhänge mit `parent_id`; audio: whisper; bild: vision; text: text; sonstig: keine Extraktion, `Lauf(status=uebersprungen, fehler="Dateityp nicht unterstützt")`), überspringt bereits vorhandene Methoden. Jede Methode einzeln in try/except → `Lauf(status=fehler)`; ein Fehler stoppt nicht die anderen Methoden. Jede Methode schreibt `Lauf` mit Dauer und Modell.
  - `dateien_finden(pfad: Path) -> list[Path]` – rekursiv, ohne versteckte Dateien und ohne `processed/`, sortiert nach Pfad.
  - `ingest_ordner(session, pfad: Path, s, clients, methoden=None, bei_datei: Callable[[int, int, str], None] | None = None, soll_abbrechen: Callable[[], bool] | None = None) -> IngestBilanz` (dataclass: neu, bekannt, fehler: int).
  - CLI: `vfm ingest PFAD [--methode schnell|docling|vision|alle]` (Datei oder Ordner, rich-Fortschrittsbalken, am Ende Bilanz); `vfm text ID [--vergleich] [--aktiv METHODE]` (ohne `--vergleich`: aktiver Text; mit: Tabelle Methode | Zeichen | Dauer | Modell | erste 300 Zeichen; `--aktiv` ruft `aktiv_setzen`).

- [ ] **Step 1: Tests** (Fake-Clients):
  - `test_kaputtes_pdf_bricht_nicht_ab` – Ordner mit `kaputt.pdf` (`%PDF` + Müll) und `notiz.txt` → Bilanz `neu=2`, für notiz.txt aktive Extraktion vorhanden, für kaputt.pdf `Lauf.status == fehler` oder leere schnell-Extraktion, kein Exception.
  - `test_docx_wird_uebersprungen` – `Lauf.status == uebersprungen`.
  - `test_anhang_und_einzeldatei_ein_dokument` – Mail mit Anhang `a.pdf` und dieselbe `a.pdf` im Ordner → 1 PDF-Dokument; `parent_id` gesetzt (vom ersten Auftreten).
  - `test_scan_pdf_loest_docling_aus` – schnell liefert 10 Zeichen (monkeypatch) → docling aufgerufen.
  - `test_zweiter_lauf_ueberspringt` – zweimal `ingest_ordner` → beim zweiten `neu=0, bekannt=2`, keine neuen Läufe für vorhandene Methoden.
  - CLI: `test_vfm_ingest_ordner` → Exit 0, Ausgabe enthält „neu: 2“; `test_vfm_text_vergleich` → Tabelle mit beiden Methoden.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: Ingest-Ablauf für Dateien und Ordner, vfm ingest/text`.

---

### Task 13: GUI – Dokumente, Detail, Upload, Ordner-Import

**Files:**
- Create: `app/web/routes_dokumente.py`, `app/web/routes_upload.py` (neu geschrieben, Muster aus alter Version in git-History `511301f`), Templates `dokumente.html`, `dokument_detail.html`, `upload.html`, `lauf_status.html`
- Modify: `app/web/templates/base.html` (Navigation: Dokumente, Upload, Entitäten, Suche, SQL, Status; „Jetzt abrufen“-Button raus), `app/main.py`
- Test: `tests/web/test_routes_dokumente.py`, `tests/web/test_routes_upload.py`

**Interfaces:**
- Consumes: `ingest_datei`, `ingest_ordner`, `progress`.
- Produces:
  - `GET /` → Redirect `/dokumente`. `GET /dokumente?typ=&q=&seite=` – Tabelle: Dateiname, Typ, Datum (metadaten.datum oder erstellt_am), Anhang-von, Text ✓/–, Entitäten-Zahl, Embedding ✓/– (aktuelles Modell), Analyse ✓/–; `q` filtert Dateiname ILIKE.
  - `GET /dokumente/{id}` – Metadaten, Original-Vorschau (`<iframe>` PDF, `<img>` Bild, `<audio>` Audio, Mail: Kopf + Anhänge als Links), Reiter je Extraktionsmethode (Text in `<pre>`, aktive markiert, Button „als aktiv setzen“ → `POST /dokumente/{id}/aktiv/{extraktion_id}`), Platzhalter-Abschnitte für Entitäten/Analysen (Tasks 17/22 füllen), Lauf-Log-Tabelle.
  - `GET /dokumente/{id}/datei` – Original mit MIME, `Content-Disposition: inline`.
  - `GET /upload`, `POST /upload` (mehrere Dateien, Feld `methode`) → Hintergrund-Thread, Redirect `/laeufe/{schluessel}`; `POST /upload/ordner` (importiert `material_pfad`) → gleiches; `GET /laeufe/{schluessel}` + `/daten` (JSON: schritt, erledigt, gesamt, fehlgeschlagen, fertig, fehler); `POST /laeufe/{schluessel}/abbrechen`. Nur ein Ordner-Lauf gleichzeitig (Lock, wie früher `watchfolder_im_hintergrund_starten`).

- [ ] **Step 1: Tests** (TestClient, `app.dependency_overrides[get_session]`, Ingest im Thread per monkeypatch synchron):
  - `test_liste_zeigt_dokument` – Dateiname im HTML.
  - `test_detail_zeigt_beide_methoden` – „schnell“ und „docling“ als Reiter.
  - `test_datei_auslieferung_mime` – PDF → `application/pdf`.
  - `test_upload_startet_lauf` → 303 auf `/laeufe/…`, danach `/daten` `fertig: true`, Dokument existiert.
  - `test_zweiter_ordnerlauf_abgelehnt` – Lock gehalten → Meldung „läuft bereits“.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS. Danach manuell im Browser `docker compose up -d` → Upload eines PDFs, Detailseite prüfen.
- [ ] **Step 5: Commit** `feat: GUI für Dokumente, Detailansicht und Upload`.

---

### Task 14: SQL-Seite und `vfm sql`

**Files:**
- Create: `app/sql/abfrage.py`, `app/sql/beispiele.py`, `app/web/routes_sql.py`, Template `sql.html`
- Modify: `app/cli.py`
- Test: `tests/sql/test_abfrage.py`, `tests/web/test_routes_sql.py`

**Interfaces:**
- Produces:
  - `@dataclass SqlErgebnis(spalten: list[str], zeilen: list[tuple], abgeschnitten: bool, dauer_ms: int)`.
  - `sql_ausfuehren(engine: Engine, sql: str, limit: int = 500, timeout_ms: int = 10000) -> SqlErgebnis` – eigene Verbindung, `SET TRANSACTION READ ONLY`, `SET LOCAL statement_timeout`, `fetchmany(limit + 1)`, immer Rollback. Fehler → `SqlFehler(meldung)` mit der Postgres-Meldung (ohne SQLAlchemy-Präfix).
  - `BEISPIELE: list[tuple[str, str]]` (Titel, SQL) – mind.: Dokumente je Typ; größte Dokumente; Mails nach Absender; häufigste Entitäten je Label; Dokumente mit IBAN; Volltextsuche mit `websearch_to_tsquery('german', 'Rechnung')`; Dokumente ohne Text.
  - Engine für die Seite: `create_engine(s.sql_readonly_url or s.database_url)`.
  - `GET /sql`, `POST /sql` (Form `sql`) – Textarea, Beispiel-Buttons, Ergebnistabelle, Hinweis bei `abgeschnitten`. CLI `vfm sql "…" [--limit N]`.

- [ ] **Step 1: Tests:** `test_select_funktioniert`, `test_insert_wird_abgelehnt` (SqlFehler, Meldung enthält „read-only“), `test_limit_schneidet_ab` (`generate_series(1,10)`, limit 3 → 3 Zeilen, `abgeschnitten`), `test_timeout` (`pg_sleep(2)`, timeout 100 ms → SqlFehler), `test_beispiele_laufen_alle` (jedes Beispiel gegen leere DB ohne Fehler), Web: `test_sql_seite_zeigt_tabelle`.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: Read-only-SQL in GUI und CLI`.

---

### Task 15: NER – Muster (IBAN, Telefon, E-Mail, Geldbetrag, Datum)

**Files:**
- Create: `app/ner/muster.py`, `app/ner/treffer.py`
- Modify: `pyproject.toml` (`schwifty`, `phonenumbers`, `dateparser`)
- Test: `tests/ner/test_muster.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Treffer(label: str, text: str, start: int, ende: int, normalisiert: str | None = None, score: float | None = None)` in `treffer.py`.
  - Labels (gelten projektweit, auch für GliNER und LLM): `person`, `organisation`, `ort`, `datum`, `geldbetrag`, `iban`, `telefon`, `email`.
  - `finde_muster(text: str) -> list[Treffer]` – IBAN: Regex für Kandidaten (mit Leerzeichen-Gruppen), Validierung mit `schwifty.IBAN`, `normalisiert` = kompakt; Telefon: `phonenumbers.PhoneNumberMatcher(text, "DE")`, normalisiert E.164; E-Mail: Regex, lowercase; Geldbetrag: `(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s?(?:€|EUR|Euro)` und `(?:€|EUR)\s?<zahl>`, normalisiert `"1234.50 EUR"`; Datum: `\d{1,2}\.\d{1,2}\.\d{2,4}`, `\d{4}-\d{2}-\d{2}`, `\d{1,2}\.\s?(Januar|…|Dezember)\s\d{4}`, normalisiert ISO via `dateparser.parse(…, languages=["de"])`. `score=1.0`. Sortiert nach start, Überlappungen: längerer Treffer gewinnt.

- [ ] **Step 1: Tests:**
  - `test_gueltige_iban_mit_leerzeichen` – „DE89 3704 0044 0532 0130 00“ → label iban, normalisiert „DE89370400440532013000“.
  - `test_ungueltige_iban_wird_verworfen` – Prüfziffer falsch → kein Treffer.
  - `test_telefon_national` – „040 123456-78“ → normalisiert „+494012345678“.
  - `test_geldbetrag_varianten` – „1.234,50 €“, „EUR 300“, „12 Euro“ → normalisiert „1234.50 EUR“, „300.00 EUR“, „12.00 EUR“.
  - `test_datum_ausgeschrieben` – „3. März 2024“ → „2024-03-03“.
  - `test_offsets_stimmen` – für jeden Treffer `text[t.start:t.ende] == t.text`.
  - `test_iban_ist_keine_telefonnummer` – IBAN-Text erzeugt keinen telefon-Treffer (Überlappungsregel).
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: Muster-NER für IBAN, Telefon, E-Mail, Geldbeträge, Daten`.

---

### Task 16: NER – GliNER

**Files:**
- Create: `app/ner/gliner.py`
- Modify: `pyproject.toml` (Paket laut Spike), `scripts/modelle_laden.py`
- Test: `tests/ner/test_gliner.py`

**Interfaces:**
- Produces:
  - `GLINER_LABELS: dict[str, str]` – internes Label → Modell-Label (Sprache laut Spike), Default-Labels `person, organisation, ort, datum, geldbetrag`.
  - `class GlinerNer: __init__(modell: str, schwelle: float = 0.5)`; `finde(text: str, labels: list[str] | None = None) -> list[Treffer]` – lazy Laden; Text in Fenster à 1200 Zeichen mit 100 Überlappung (an Wortgrenzen), Offsets auf Gesamttext zurückrechnen, Duplikate aus Überlappung (gleiches label/start/ende) entfernen.

- [ ] **Step 1: Tests:** `test_offsets_ueber_fenster` (Fake-Modell, das jedes Vorkommen von „Müller“ meldet; Text 3000 Zeichen mit „Müller“ bei Position 2500 → Treffer `start == 2500`), `test_keine_duplikate_aus_ueberlappung`, `test_labels_werden_uebersetzt` (Fake prüft übergebene Modell-Labels), `@pytest.mark.modelle test_gliner_deutsch` („Angela Merkel traf in Berlin Vertreter der Siemens AG.“ → person, ort, organisation).
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: GliNER-NER mit Fensterung`.

---

### Task 17: NER – LLM, Ablauf, `vfm ner`, Entitäten-GUI

**Files:**
- Create: `app/ner/llm_ner.py`, `app/ner/ablauf.py`, `app/web/routes_entitaeten.py`, Template `entitaeten.html`
- Modify: `app/cli.py`, `dokument_detail.html` (Entitäten-Abschnitt + Markierung)
- Test: `tests/ner/test_llm_ner.py`, `test_ablauf.py`, `tests/web/test_routes_entitaeten.py`

**Interfaces:**
- Produces:
  - `llm_ner(client: LLMClient, text: str, labels: list[str]) -> list[Treffer]` – Schema `LlmEntitaeten{entitaeten: list[{label: str, text: str}]}`; Prompt nennt die Labels mit deutscher Erklärung; Text > 6000 Zeichen in Fenster teilen; Offsets: alle Vorkommen per `re.finditer(re.escape(text))`; Treffer, die nicht im Text vorkommen, verwerfen (Halluzination) und Anzahl in `Lauf.roh_output["verworfen"]` melden; Labels außerhalb der Liste verwerfen.
  - `ner_ausfuehren(session, s: Settings, methoden: set[NerMethode], dokument_id: int | None = None, labels: list[str] | None = None, bei_dokument=None, soll_abbrechen=None) -> NerBilanz` – für aktive Extraktionen (alle oder eine), löscht vorhandene Entitäten gleicher (extraktion, methode), speichert neue, schreibt `Lauf`; leerer Text → `Lauf(uebersprungen)`.
  - `vergleich(session, extraktion_id: int) -> list[VergleichZeile]` – `VergleichZeile(label, text_normalisiert, methoden: set[str])`, Normalisierung casefold + Whitespace.
  - CLI `vfm ner [--methode gliner|muster|llm|alle] [--dokument ID] [--labels a,b] [--vergleich]`.
  - GUI: `GET /entitaeten?label=&q=` – je Label Tabelle Text | Anzahl | Dokumente (Links), Filter nach Methode; Detailseite: Text der aktiven Extraktion mit `<mark class="ent-{label}">`, Umschalter je Methode (vanilla JS, Daten als JSON im Template), Vergleichstabelle; Button „NER starten“ → `POST /dokumente/{id}/ner` (synchron für ein Dokument).

- [ ] **Step 1: Tests:** `test_halluzination_wird_verworfen` (LLM liefert „Hans Wurst“, nicht im Text → 0 Treffer, verworfen=1), `test_alle_vorkommen` (Name 2× im Text → 2 Treffer), `test_fremdes_label_verworfen`, `test_ner_ersetzt_alte_entitaeten` (zweimal laufen → keine Duplikate), `test_leerer_text_uebersprungen`, `test_vergleich_methoden` (muster+llm finden dieselbe IBAN → eine Zeile mit beiden Methoden), Web `test_entitaeten_seite_gruppiert`, `test_markierung_im_detail` (`<mark class="ent-iban">` im HTML).
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: LLM-NER, NER-Ablauf mit Vergleich, Entitäten-GUI`.

---

### Task 18: Embeddings erzeugen, `vfm embed`

**Files:**
- Create: `app/embed/index.py`
- Modify: `app/cli.py`
- Test: `tests/embed/test_index.py`

**Interfaces:**
- Produces:
  - `embed_ausfuehren(session, client: EmbeddingClient, nur_fehlende: bool = True, bei_fortschritt=None, soll_abbrechen=None) -> EmbedBilanz(neu: int, vorhanden: int, dimension: int | None)` – alle Chunks aktiver Extraktionen ohne Embedding für `client.model`, in Batches von `client.batch`, ein `Lauf` pro Aufruf (nicht pro Chunk) mit Modell und Dauer.
  - `vorhandene_modelle(session) -> list[tuple[str, int]]` (Modell, Anzahl).
  - CLI `vfm embed [--alle-neu]` – Fortschrittsbalken, am Ende Modell, Dimension, Anzahl; listet zusätzlich `vorhandene_modelle`.

- [ ] **Step 1: Tests** (respx): `test_nur_fehlende` (2 Chunks, einer hat schon Embedding für Modell → 1 Request mit 1 Input), `test_anderes_modell_neu` (Embedding für „a“ vorhanden, Client „b“ → beide neu), `test_keine_chunks` → `neu=0`, kein Request.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: Embeddings je Modell erzeugen`.

---

### Task 19: Suche (Volltext, semantisch, Rerank), `vfm suche`

**Files:**
- Create: `app/embed/suche.py`, `app/embed/volltext.py`
- Modify: `app/cli.py`
- Test: `tests/embed/test_suche.py`, `test_volltext.py`

**Interfaces:**
- Produces:
  - `@dataclass SuchTreffer(chunk_id, dokument_id, dateiname, text, vektor_rang: int | None, vektor_score: float | None, rerank_rang: int | None, rerank_score: float | None, snippet: str | None = None)`.
  - `volltext_suche(session, anfrage: str, limit: int = 20) -> list[SuchTreffer]` – `websearch_to_tsquery('german', :q)`, `ts_rank`, `ts_headline` → snippet (`<b>`-Markierung), `vektor_*`/`rerank_*` None.
  - `class KeineEmbeddingsFehler(Exception)` mit Meldung „Für Modell {m} gibt es noch keine Embeddings – erst `vfm embed` ausführen“.
  - `semantische_suche(session, anfrage: str, embed: EmbeddingClient, reranker: Reranker, top_n: int, top_k: int, dokument_typ: DokumentTyp | None = None) -> list[SuchTreffer]` – nur `Embedding.modell == embed.model`; keine → `KeineEmbeddingsFehler`; Ränge 1-basiert; bei `KeinReranker` bleibt Vektor-Reihenfolge, `rerank_*` None.
  - CLI `vfm suche "…" [--volltext] [--top-n] [--top-k] [--ohne-rerank]` – Tabelle Rang | Vektor-Rang | Score | Rerank-Score | Dokument | Ausschnitt (zeigt Rangsprünge, z. B. „12 → 1“).

- [ ] **Step 1: Tests:** `test_volltext_stemming` („Rechnungen“ findet „Rechnung“), `test_semantisch_nur_aktuelles_modell` (Embeddings für „a“ und „b“, Client „b“ → nur Chunks mit „b“), `test_keine_embeddings_meldung`, `test_rerank_aendert_reihenfolge` (Fake-Reranker dreht um → `rerank_rang` 1 bei `vektor_rang` 2), `test_ohne_rerank_vektor_reihenfolge`, `test_typ_filter`.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: Volltext- und semantische Suche mit Rerank`.

---

### Task 20: RAG, `vfm frage`, Such-GUI

**Files:**
- Create: `app/embed/rag.py`, `app/web/routes_suche.py`, Template `suche.html` (neu)
- Modify: `app/cli.py`
- Test: `tests/embed/test_rag.py`, `tests/web/test_routes_suche.py`

**Interfaces:**
- Produces:
  - `@dataclass RagAntwort(text: str, quellen: list[SuchTreffer])`.
  - `antwort_erzeugen(llm: LLMClient, frage: str, treffer: list[SuchTreffer], max_zeichen_je_quelle: int = 2000) -> RagAntwort` – `chat_text`; System-Prompt: nur aus Quellen antworten, Quellen als [1], [2] zitieren (Nummer = Position in `treffer`), sonst „Dazu finde ich in den Dokumenten nichts.“; keine Treffer → diese Antwort ohne LLM-Aufruf.
  - CLI `vfm frage "…"` – Antwort + Quellenliste (Nummer, Dateiname, Dokument-ID).
  - GUI `GET /suche?q=&modus=volltext|semantisch&rerank=1` – Reiter, Ergebnisliste mit Rangspalten, Links zur Detailseite; Button „Antwort generieren“ → `POST /suche/antwort` (JSON `{frage}` → `{text_html, quellen}`; Fußnoten als Links). `KeineEmbeddingsFehler`/`ProviderFehler` als Hinweisbox.

- [ ] **Step 1: Tests:** `test_quellen_nummeriert_im_prompt` (respx-Request enthält „[1]“ und „[2]“ mit Dateinamen), `test_keine_treffer_kein_llm_call`, `test_quelle_gekuerzt`, Web `test_suche_seite_volltext`, `test_suche_ohne_embeddings_zeigt_hinweis`, `test_antwort_endpoint`.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: RAG-Antworten in CLI und Such-GUI`.

---

### Task 21: Agent-API für Hermes

**Files:**
- Create: `app/api/routes.py`
- Modify: `app/main.py`
- Test: `tests/api/test_routes.py`

**Interfaces:**
- Consumes: `volltext_suche`, `semantische_suche`, `antwort_erzeugen`.
- Produces (alle unter `/api`, Pydantic-Response-Modelle mit Feldbeschreibungen, damit `/docs` als Tool-Doku taugt):
  - `GET /api/suche?q=&modus=semantisch|volltext&top_k=8` → `[{dokument_id, dateiname, typ, ausschnitt, score}]`.
  - `GET /api/dokumente/{id}` → `{id, dateiname, typ, metadaten, text, entitaeten: [{label, text, methode}], analysen: {art: ergebnis}, anhaenge: [id], parent_id}`; `text` auf 20000 Zeichen gekürzt, Feld `text_gekuerzt: bool`.
  - `GET /api/entitaeten?label=&q=&limit=50` → `[{label, text, anzahl, dokument_ids}]`.
  - `POST /api/frage {frage}` → `{antwort, quellen: [{nummer, dokument_id, dateiname}]}`.
  - Auth: wenn `api_token` gesetzt, `Authorization: Bearer <token>` Pflicht, sonst 401 `{"detail": "API-Token fehlt oder falsch"}`; ohne Token offen.

- [ ] **Step 1: Tests:** je Endpoint ein Happy-Path; `test_token_pflicht_wenn_gesetzt` (401 ohne, 200 mit); `test_text_gekuerzt`; `test_openapi_enthaelt_beschreibungen` (`/openapi.json` hat `description` an `q`).
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: JSON-API für den Recherche-Agenten`.

---

### Task 22: LLM-Analyse, `vfm analyse`, `vfm pipeline`

**Files:**
- Create: `app/analyse/kategorien.py`, `app/analyse/ablauf.py`, `config/kategorien.yaml`
- Modify: `app/cli.py`, `dokument_detail.html`, `app/web/routes_dokumente.py`, `pyproject.toml` (`pyyaml`)
- Test: `tests/analyse/test_kategorien.py`, `test_ablauf.py`

**Interfaces:**
- Produces:
  - `config/kategorien.yaml`: Liste `{name, beschreibung}` mit Vertrag, Rechnung, Korrespondenz, Protokoll, Privat, Sonstiges.
  - `lade_kategorien(pfad: str) -> list[Kategorie]` (dataclass name, beschreibung); leer/fehlt → `ValueError` mit Pfad.
  - `zusammenfassen(llm, text: str) -> dict` → `{"text": …}` (chat_text, 3–5 Sätze, Deutsch; Text > 12000 Zeichen: erst Abschnitte zusammenfassen, dann die Teil-Zusammenfassungen).
  - `klassifizieren(llm, text: str, kategorien: list[Kategorie]) -> dict` → `{"kategorie", "begruendung", "sicherheit"}` (chat_json mit Schema; Kategorie nicht in Liste → „Sonstiges“, `roh_kategorie` zusätzlich gespeichert).
  - `bild_beschreiben(vision: LLMClient, bild_jpeg: bytes) -> dict` → `{"text": …}` (Prompt: sachlich, was ist zu sehen, Personen nur beschreiben, nicht identifizieren).
  - `analyse_ausfuehren(session, s, arten: set[AnalyseArt], dokument_id: int | None = None, bei_dokument=None, soll_abbrechen=None) -> AnalyseBilanz` – bildbeschreibung nur für Typ bild; zusammenfassung/klassifikation nur mit nicht-leerem aktivem Text; ersetzt vorhandene Analyse gleicher Art; `Lauf` je Dokument/Art.
  - CLI `vfm analyse [--art zusammenfassung|klassifikation|bildbeschreibung|alle] [--dokument ID]`; `vfm pipeline PFAD` = ingest → ner (gliner, muster) → embed → analyse (alle).
  - GUI: Detailseite zeigt Analysen + Button „Analysieren“ (`POST /dokumente/{id}/analyse`, synchron, ein Dokument); Dokumentliste bekommt Spalte/Filter „Kategorie“.

- [ ] **Step 1: Tests:** `test_kategorien_laden`, `test_kategorien_fehlen` (ValueError mit Pfad), `test_unbekannte_kategorie_wird_sonstiges`, `test_bildbeschreibung_nur_fuer_bilder` (PDF → keine bildbeschreibung), `test_leerer_text_keine_zusammenfassung`, `test_lange_texte_zweistufig` (respx zählt ≥ 3 Requests bei 30000 Zeichen), `test_analyse_ersetzt_alte`.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: LLM-Analyse (Zusammenfassung, Klassifikation, Bildbeschreibung) und vfm pipeline`.

---

### Task 23: Status-Seite und Hintergrund-Läufe für NER/Embed/Analyse

**Files:**
- Create: `app/web/routes_status.py`, Template `status.html`
- Modify: `app/web/routes_upload.py` (generischer Lauf-Starter), `app/main.py`
- Test: `tests/web/test_routes_status.py`

**Interfaces:**
- Produces:
  - `lauf_starten(schluessel: str, funktion: Callable[[Session, Callable, Callable], object]) -> bool` in `routes_upload.py` – Thread mit eigener Session, setzt progress; False wenn Lauf mit gleichem Schlüssel aktiv.
  - `GET /status` – je Rolle Provider/Backend/Modell/URL (Keys maskiert: erste 4 Zeichen + „…“), Zählerstände wie `vfm status`, Buttons: „Verbindung prüfen“ (`POST /status/check`, synchron → Tabelle wie `vfm check`), „NER für alle“, „Embeddings erzeugen“, „Analyse für alle“ (je → `lauf_starten`, Redirect `/laeufe/{schluessel}`). Hinweis: Läufe aus der CLI erscheinen hier nicht.

- [ ] **Step 1: Tests:** `test_key_maskiert` (Key nicht im HTML), `test_check_button` (respx, Ergebnis-Tabelle), `test_embed_lauf_startet` (Redirect, `/laeufe/embed/daten` fertig), `test_doppelter_lauf_abgelehnt`.
- [ ] **Step 2–4:** FAIL → Implementieren → PASS.
- [ ] **Step 5: Commit** `feat: Status-Seite mit Provider-Check und Hintergrund-Läufen`.

---

### Task 24: Beispiel-Fixtures und End-to-End-Lauf

**Files:**
- Create: `scripts/fixtures_erzeugen.py`, `tests/fixtures/mini/` (erzeugte Dateien, klein, committed), `tests/test_e2e.py`

**Interfaces:**
- Produces: `tests/fixtures/mini/` mit `vertrag.pdf` (Text, enthält IBAN DE89 3704 0044 0532 0130 00, Betrag „12.500,00 €“, Personen, Firma), `scan.pdf` (dieselbe Seite als Bild-PDF via pypdfium2-Render + Pillow), `mail.eml` (mit `vertrag.pdf` als Anhang, To/Cc), `sprachnachricht.m4a` (macOS `say -v Anna` + `ffmpeg`, ≤ 15 s, nennt Telefonnummer), `foto.jpg` (Pillow: Schild mit Text „Lagerhalle 7“, EXIF-GPS Hamburg). Script ist idempotent; Audio-Teil wird übersprungen, wenn `say` fehlt.

- [ ] **Step 1:** Script schreiben und ausführen; Dateien committen (zusammen < 1 MB prüfen).
- [ ] **Step 2: Test** `tests/test_e2e.py` (`@pytest.mark.modelle`, braucht laufendes Ollama + lokale Modelle): `vfm pipeline tests/fixtures/mini` per CliRunner → Exit 0; danach: 5 Dokumente + Anhang dedupliziert (vertrag.pdf einmal); IBAN von `muster` gefunden; `vfm suche "Lagerhalle"` findet foto.jpg; `vfm frage "Wie hoch ist der Vertragswert?"` enthält „12.500“; Klassifikation von vertrag.pdf = „Vertrag“.
- [ ] **Step 3:** `uv run pytest -m modelle tests/test_e2e.py` gegen Host-Ollama → PASS; dann gleiches mit `PROVIDER=cortecs` (wenn Key vorhanden) → PASS oder Abweichungen in `spike-ergebnisse.md` notieren.
- [ ] **Step 4: Commit** `test: Mini-Beispielsatz und End-to-End-Test`.

---

### Task 25: Multi-Arch-Images und USB-Paket

**Files:**
- Create: `scripts/image_bauen.sh`, `scripts/usb_paket_bauen.sh`, `scripts/einspielen.sh`, `scripts/einspielen.ps1`

**Interfaces:**
- Produces:
  - `scripts/image_bauen.sh amd64|arm64` – `docker buildx build --platform linux/<arch> --provenance=false --sbom=false -t vfm-pipeline:latest --load .` und `docker save | gzip > dist/vfm-pipeline-<arch>.tar.gz`; danach Architektur per `docker image inspect` prüfen (Abbruch bei Abweichung).
  - `scripts/usb_paket_bauen.sh ZIEL` – kopiert beide App-tars, `pgvector/pgvector:pg16` je Arch (Digest-Pull-Muster aus AGENTS.md), `ollama/ollama`-Image amd64, Ollama-Modelle (`~/.ollama/models` gefiltert auf die Profil-Modelle per Manifest-Dateien), Repo-Snapshot (`git archive HEAD`), `ANLEITUNG.md`.
  - `einspielen.sh` / `.ps1` – erkennt Architektur, `docker load` passende tars, kopiert Ollama-Modelle nach `~/.ollama/models` (fragt vorher), entpackt Repo, legt `.env` aus `.env.example` an.
- [ ] **Step 1:** Scripte schreiben. **Step 2: Verifizieren:** amd64- und arm64-Image bauen; arm64 lokal `docker load` + `vfm check`; amd64 auf dem Server (durch Nutzer) `vfm check`. Offline-Test: `docker compose up -d` mit abgeschaltetem WLAN, `vfm ingest tests/fixtures/mini` → keine Download-Versuche im Log.
- [ ] **Step 3: Commit** `build: Multi-Arch-Images und USB-Offline-Paket`.

---

### Task 26: Dokumentation

**Files:**
- Modify: `README.md` (neu), `AGENTS.md` (neu)
- Create: `docs/workshop/tag1.md`, `tag2.md`, `tag3.md`

- [ ] **Step 1:** README: Zweck; Setup in 5 Schritten (Docker installieren · Ollama + `ollama pull <Profil-Modelle>` oder USB-Paket · `cp .env.example .env`, Provider wählen · `docker compose up -d` · `docker compose exec app vfm check`) · Material nach `./material` legen · GUI-URL `http://localhost:8999` · Befehlsübersicht · Fehlerbehebung (Ollama nicht erreichbar, zu wenig RAM in Docker Desktop/Colima, Windows-Hinweise).
- [ ] **Step 2:** AGENTS.md für die neue Struktur (Verzeichnisbaum, zentrale Konzepte: Rollen/Profile, aktive Extraktion, Embeddings je Modell, schrittweiser Ablauf, Tests, Deployment/USB).
- [ ] **Step 3:** Spickzettel: Tag 1 (check, ingest mit Methodenvergleich, text --vergleich, GUI-Detail), Tag 2 (SQL-Beispiele, `vfm ner --methode alle --vergleich`, Muster vs. GliNER vs. LLM, Entitäten-Seite), Tag 3 (embed mit zwei Modellen, suche mit/ohne Rerank, frage, API-Aufrufe für Hermes per curl). Je Tag 3–5 Übungsaufgaben.
- [ ] **Step 4:** Alle Befehle aus den Spickzetteln einmal gegen den Mini-Satz ausführen.
- [ ] **Step 5: Commit** `docs: README, AGENTS.md und Workshop-Spickzettel`.
