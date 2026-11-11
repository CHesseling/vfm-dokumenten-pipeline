# Umbau: vfm_pipeline als Workshop-Pipeline für Dokumenten-Analyse mit LLMs

## Context

Das Repo ist eine Kopie des Gerichtstermine-Auswerters: alles ist auf Verfahren, Aktenzeichen,
Wochenpläne und ein Graph-Postfach zugeschnitten. Für das Datenseminar (vfm, 30.11.–2.12.2026,
Claus & Jan) soll daraus eine **generische Rechercheakten-Pipeline** werden, an der Teilnehmende
die Schritte **Ingest/OCR → NER → Embeddings/RAG → LLM-Analyse → Anzeige** selbst ausprobieren,
teils in der GUI, teils in der CLI. Material: heterogene Akten (PDF Text+Scan, E-Mails,
Sprachnachrichten, Fotos), **wird separat verteilt** (USB/Download → Watchfolder), nicht im Repo.
Jeder Schritt muss mit **lokalen Modellen (Ollama)** und mit **Cortecs** (OpenAI-kompatibel)
laufen, umschaltbar ohne Code-Änderung.

Entscheidungen des Nutzers:
- Generischer Fall statt Gerichtstermine; Gerichts-Code, Graph/IMAP, Scheduler fliegen raus.
- Setup: eigene Laptops (Docker) **und** gemeinsamer Server als Ausweichlösung.
- Ein großes Docker-Image (CPU-PyTorch, Modelle beim Build vorgeladen, offline-fähig).
- NER: GliNER2 + Python-Pakete/Regex (IBAN, Telefon, Datum, Geldbeträge) + LLM-NER zum Vergleich.
- LLM-Analyse: Zusammenfassung, Klassifikation, Bildbeschreibung.
- JSON-API für den Hermes-Agenten (Tag 3).
- SQL-Seite in der GUI (read-only) für Tag 2.
- Nicht im Repo: MCP, Classifier (JEV), OpenSanctions-Abgleich.
- Laptops unbekannt → konservativ: kleine Ollama-Modelle, amd64 + arm64, Cortecs als Fallback.
- Offline: USB-Paket mit allem (Images + Ollama-Modelle + Einspiel-Skript).
- Cortecs-Key: gemeinsam oder je Person offen → einfach per `.env`, beides geht.
- Klassifikation: Kategorien frei konfigurierbar, Material Deutsch.

## Architektur (Zielbild)

```
app/
  config.py            Settings je Rolle (chat, vision, embed, rerank, transcribe), Provider-Presets
  providers/           llm_client.py (bestehend, verschoben), embeddings.py, rerank.py,
                       transcribe.py, factory.py (baut Clients aus Settings; CLI-Override --provider)
  ingest/              dateitypen.py (Erkennung), speichern.py (Dedup per SHA-256),
                       pdf.py (schnell=pypdfium2 | docling | vision), eml.py (eml_parse bestehend,
                       Anhänge → Kind-Dokumente, rekursiv), audio.py (faster-whisper | API),
                       bild.py (docling-OCR | vision), watchfolder.py (bestehend, angepasst)
  ner/                 gliner.py, muster.py (schwifty IBAN, phonenumbers, Datum, Geldbetrag,
                       E-Mail), llm_ner.py, vergleich.py
  embed/               chunking.py (generisch, Absätze/Tokenfenster), index.py, suche.py
                       (Vektor top_n → Rerank → top_k, Scores vor/nach Rerank sichtbar),
                       volltext.py (Postgres tsvector 'german'), rag.py (Antwort mit Fußnoten)
  analyse/             zusammenfassung.py, klassifikation.py (Kategorien konfigurierbar),
                       bildbeschreibung.py
  models/              siehe Datenmodell
  cli.py               Typer-App "vfm"
  web/                 Routen + Templates (bestehendes NDR-Design in base.html bleibt)
  api/                 JSON-Endpunkte für Hermes
  progress.py          bestehend
```

### Datenmodell (neue Alembic-Basis-Migration, alte Migrationen löschen)
- `Dokument`: id, sha256 (unique), dateiname, typ (pdf/eml/audio/bild/text/sonstig), mime,
  parent_id (Anhang einer Mail), metadaten JSON (Absender, Betreff, Datum, EXIF…), Datei auf
  Volume `/data/dateien/<sha256>` (nicht als Blob – Audios/Fotos sind groß), created_at.
- `TextExtraktion`: dokument_id, methode (schnell/docling/vision/whisper/eml/text), text, modell,
  dauer_ms, ist_aktiv. Mehrere je Dokument → Methoden direkt vergleichbar (Tag 1).
- `Chunk`: textextraktion_id, position, text, start, ende, tsvector (Volltext). Chunking direkt
  beim Ingest der aktiven Extraktion → Volltext/SQL ab Tag 1 nutzbar.
- `Embedding`: chunk_id, modell, vektor `Vector()` **ohne feste Dimension** – mehrere Modelle
  parallel speicherbar, Suche filtert per modell (Workshop-Vergleich Ollama vs. Cortecs).
- `Entitaet`: textextraktion_id (Offsets beziehen sich auf genau diesen Text), methode (gliner/muster/llm), label, text, normalisiert, start, ende, score.
- `Analyse`: dokument_id, art (zusammenfassung/klassifikation/bildbeschreibung), modell, ergebnis JSON.
- `Lauf` (Audit, ersetzt ExtractionRun): schritt, dokument_id, provider, modell, dauer_ms,
  status, fehler, roh_output.

### Provider-Konfiguration
- Je Rolle `<ROLLE>_BASE_URL / _MODEL / _API_KEY` (CHAT, VISION, EMBED, RERANK, TRANSCRIBE),
  Vorlagen `.env.ollama.example` und `.env.cortecs.example`. Ollama läuft auf dem Laptop-Host
  (Metal-GPU, `host.docker.internal:11434/v1`), Compose-Profil `ollama` als Container für den Server.
- Rerank-Backend: `local` (sentence-transformers CrossEncoder, im Image vorgeladen) | `api`
  (Cohere-Format, bestehender rerank.py) | `none` – Ollama hat kein Rerank-Endpoint.
- Transkription: `local` (faster-whisper, Modell `small`, im Image) | `api` (`/audio/transcriptions`).
- Beim Implementieren prüfen, welche Endpunkte Cortecs tatsächlich anbietet (Embeddings, Audio,
  Vision); was fehlt, fällt auf `local` zurück – dokumentiert in den .env-Vorlagen.
- `LLMClient` aus `app/extraction/llm_client.py` wird übernommen (Zeitbudget, Retries,
  Structured-Outputs-Fallback bei HTTP 400 – passt für Ollama). Umbenennung `vllm_*` → `chat_*`.
  Ergänzen: `chat_text()` (Zusammenfassung/RAG brauchen Freitext, der Client kann heute nur
  JSON), MIME-Parameter für Bilder statt fest `image/png`, Thinking bei Qwen3-artigen Modellen aus.
- `EmbeddingClient`: Batching (Liste von Inputs je Request).
- `Settings` wird neu gebaut (heute Pflichtfelder graph_*/vllm_*), nicht nur umbenannt.
- Standardmodelle Ollama klein (Chat/Vision ~4B-Klasse, Embedding z. B. bge-m3 oder
  qwen3-embedding:0.6b); Reranker lokal: kleiner mehrsprachiger Cross-Encoder, nicht bge-reranker-v2-m3.

### CLI (`vfm`, Typer, `docker compose exec app vfm …`)
| Befehl | Workshop-Block |
|---|---|
| `vfm check` – testet jede Rolle (erreichbar, Modell da, Embedding-Dimension) | Tag 1, Docker starten |
| `vfm ingest <pfad> [--methode schnell\|docling\|vision\|alle]` | Tag 1 |
| `vfm text <id> [--vergleich]` – Methoden nebeneinander, Dauer | Tag 1 |
| `vfm sql "SELECT …"` | Tag 2 |
| `vfm ner [--methode gliner\|muster\|llm\|alle] [--labels …] [--dokument id]` | Tag 2 |
| `vfm embed [--modell …]` | Tag 3 |
| `vfm suche "…" [--top-n --top-k --ohne-rerank]` – zeigt Ränge vor/nach Rerank | Tag 3 |
| `vfm frage "…"` – RAG-Antwort mit Quellen | Tag 3 |
| `vfm analyse [--art …]` | Tag 3/4 |
| `vfm status` – Dokumente je Typ/Schritt | alle |

Alle Befehle: `--provider ollama|cortecs` überschreibt die .env, Ausgabe mit `rich`-Tabellen.

### GUI (bestehendes FastAPI/Jinja/vanilla-JS-Muster, NDR-Design)
- **Dokumente**: Liste mit Filtern (Typ, Status je Schritt, Entität), Upload (Drag&Drop, alle
  Typen) + Watchfolder-Button mit Fortschritt (bestehendes Muster aus routes_upload.py).
- **Dokument-Detail**: Original (PDF/Bild inline, Audio-Player), Textextraktionen je Methode
  nebeneinander, Entitäten farbig im Text markiert (je Methode umschaltbar), Analysen, Lauf-Log.
- **Entitäten**: Übersicht nach Label, Häufigkeit, „kommt vor in“-Dokumenten.
- **Suche**: Volltext | Semantisch (Rerank an/aus, Scores sichtbar) + „Antwort generieren“ (RAG).
- **SQL**: read-only (eigene DB-Rolle mit SELECT-Rechten, `statement_timeout`, Zeilenlimit),
  Beispiel-Queries als Buttons.
- **Einstellungen/Status**: aktive Provider und Modelle je Rolle, Ergebnis von `check`.

### Agent-API (Hermes)
`GET /api/suche?q=&modus=`, `GET /api/dokumente/{id}` (Metadaten, Text, Entitäten, Analysen),
`GET /api/entitaeten?label=&q=`, `POST /api/frage`. Optionales `API_TOKEN` (Bearer).
FastAPI-OpenAPI unter `/docs` dient als Tool-Beschreibung für den Agenten.

### Pipeline-Ablauf
Bewusst **schrittweise statt automatisch durchlaufend**: Ingest erzeugt nur Text; NER, Embed,
Analyse werden einzeln per CLI/Button gestartet (Workshop zeigt jeden Schritt einzeln).
Zusätzlich `vfm pipeline` / Button „Alles“ für den Durchlauf. Lange Läufe im Hintergrund-Thread
mit `progress.py` (bestehendes Muster), Abbrechen möglich.

## Was entfernt wird
`app/graph/`, `app/imap/`, `app/scheduler.py` (APScheduler), `app/extraction/{classify,extract,
prefilter,chunking,vollstaendigkeit,schemas}.py`, `app/pipeline/{upsert,aktenzeichen,ingest,
mail_store,dokumente}.py`, `app/models/verfahren.py`, `app/search/` (Meilisearch → Postgres-
Volltext, ein Container weniger zum Verteilen – **meine Entscheidung**), court-Templates,
`scripts/*` (court-spezifisch), alle alten Migrationen, `tmp/`-Gerichtsmails, `dist/`-Inhalte,
msal/apscheduler aus pyproject. Tests der entfernten Module ebenso.

## Wiederverwendet
- `app/extraction/llm_client.py` → `app/providers/llm_client.py` (Prompts für Korrektur-Runde neutral formulieren)
- `app/rag/embeddings.py`, `app/rag/rerank.py` → `app/providers/`
- `app/extraction/pdf_render.py` (extract_pdf_text, render_pdf_pages_to_png)
- `app/pipeline/eml_parse.py` (parse_eml_message, extract_eml_attachments)
- `app/watchfolder/client.py` (SHA-Dedup, Sortierung, processed/-Verschieben)
- `app/progress.py`, Hintergrund-Thread-/Polling-Muster aus `app/web/routes_upload.py`
- `base.html` (NDR-Design), `tests/conftest.py` (echte Postgres-Test-DB)

## Neue Abhängigkeiten
typer, rich, docling, gliner2 (Fallback `gliner` multi-v2.1, falls GliNER2 Deutsch schwach),
faster-whisper, sentence-transformers, schwifty, phonenumbers, dateparser, torch (CPU-Index via uv).

## Docker & Verteilung
- Ein Image, CPU-PyTorch; Build-Stufe lädt GliNER2-, Whisper-small-, Docling- und Reranker-Modelle
  in `/models` (HF_HOME), Laufzeit mit `HF_HUB_OFFLINE=1`.
- Compose: `db` (pgvector), `app`, Profil `ollama`. Volumes: `/data/dateien`, Watchfolder
  `./material` (Teilnehmende legen das verteilte Material dort ab).
- Verteilung offline: amd64- **und** arm64-Image als tar. Modelle in einer Stufe mit
  `--platform=$BUILDPLATFORM` laden und hineinkopieren (kein Modell-Download unter QEMU);
  torch-CPU-Index nur für amd64, `uv.lock` muss beide Plattformen auflösen. Docling-Modelle
  explizit vorladen (`artifacts_path`), sonst lädt es zur Laufzeit nach. Modelle erst bei
  Erstbenutzung in den Speicher laden. Keine Vektor-Indizes (Workshop-Größe, exakte Suche).
- **USB-Paket** (`scripts/usb_paket_bauen.sh` + `einspielen.sh`/`.ps1`): beide Image-tars,
  pgvector-Image, Ollama-Modellordner der Standardmodelle, Repo-Snapshot, Anleitung.
- SQL-Read-only-Rolle in der Migration anlegen, Abfragen zusätzlich mit `SET TRANSACTION READ ONLY`.
- Bilder: `pillow-heif` für iPhone-Fotos, vor Vision-Calls nach JPEG wandeln, EXIF per PIL.
  Docling nur für PDFs (Fotos: Vision-LLM). Audio inkl. WhatsApp-.opus über PyAV.
- Kein automatisches Watchfolder-Polling mehr; nur per Button oder CLI. CLI-Läufe erscheinen
  nicht im GUI-Fortschritt (`progress.py` ist prozesslokal) – dokumentiert.

## Doku
- README neu: Setup in 5 Schritten (Docker, Ollama-Modelle ziehen, .env wählen, `vfm check`, Material).
- `docs/workshop/` Spickzettel je Tag mit CLI-Befehlen und Übungsaufgaben (**meine Entscheidung**).
- AGENTS.md komplett neu für die neue Struktur. Design zusätzlich als
  `docs/superpowers/specs/2026-11-10-workshop-pipeline-design.md` ablegen.

## Umsetzungsreihenfolge (an Workshop-Tagen ausgerichtet)
0. **Sicherung + Spike (vor allem anderen):** Ist-Stand committen (main hat noch keinen Commit,
   sonst kein Weg zurück). Dann Machbarkeits-Spike, wegwerfbar: GliNER2 auf deutschem Text
   (sonst `gliner` multi-v2.1), Docling offline mit vorgeladenen Modellen + deutscher OCR,
   faster-whisper auf arm64, Image-Größe, Cortecs-Endpunkte (Chat/Vision/Embeddings/Audio/
   Rerank) mit echtem Key, Ollama json_schema + Bilder. Ergebnis entscheidet Modellwahl und
   Fallbacks.
1. Aufräumen + Grundgerüst: Entfernen, neues Datenmodell + Migration, Provider-Settings/Factory,
   `vfm check`, Docker-Image mit Torch und vorgeladenen Modellen.
2. Ingest (Tag 1): Dateityp-Erkennung, PDF schnell/docling/vision, EML+Anhänge, Audio, Bild;
   GUI Dokumente/Detail/Upload/Watchfolder.
3. SQL + NER (Tag 2): SQL-Seite + `vfm sql`, GliNER2, Muster, LLM-NER, Vergleich, Entitäten-GUI.
4. Embeddings/Suche/RAG (Tag 3): Chunking, Embed, Volltext, Rerank, RAG, Such-GUI, Agent-API.
5. Analyse: Zusammenfassung, Klassifikation, Bildbeschreibung (CLI + Detailseite).
6. Doku, Spickzettel, Multi-Arch-Images, Offline-Paket.

## Von mir entschieden (bitte prüfen)
- Meilisearch raus, Volltext über Postgres (`tsvector 'german'`).
- Pipeline läuft schrittweise (jeder Schritt einzeln startbar) plus „Alles“-Befehl.
- Dateien auf einem Volume statt als Blob in der DB.
- Embeddings ohne feste Dimension, mehrere Modelle parallel → Vergleich Ollama vs. Cortecs.
- Spickzettel je Workshop-Tag unter `docs/workshop/`.
- Kein Video (nicht verlangt).
- Klassifikations-Kategorien in `config/kategorien.yaml`, Startset: Vertrag, Rechnung,
  Korrespondenz, Protokoll, Privat, Sonstiges.

## Noch offen (blockiert nicht den Start)
- Specs des gemeinsamen Servers (GPU? RAM?) und Zahl der Teilnehmenden → Parallelität, Server-Ollama.
- Wo Hermes läuft und wie es die API erreicht (Laptop vs. Server).
- Cortecs-Key für den Spike in Schritt 0.

## Verifikation
- `uv run pytest` – Tests je Modul (1:1-Spiegelung), Modelle (GliNER, Whisper, Docling, Reranker)
  hinter Interfaces gemockt; echte Modelltests mit `@pytest.mark.modelle`, separat ausführbar.
- E2E lokal: `docker compose up -d`, `vfm check` mit `.env.ollama` und `.env.cortecs`,
  Mini-Beispielsatz in `tests/fixtures/`, per Skript erzeugt (Text-PDF; Scan-PDF = gerendertes
  Bild-PDF; .eml mit Anhang; Audio via macOS `say` + ffmpeg; Foto mit EXIF) durch alle Schritte: `vfm ingest --methode alle`, `vfm ner --methode alle`,
  `vfm embed`, `vfm suche`, `vfm frage`, `vfm analyse`; GUI-Seiten im Browser durchklicken;
  `/api/suche` per curl.
- Offline-Test: Container mit `--network none` (außer Ollama auf Host) startet und ingestiert.
- Image auf amd64 (Server) und arm64 (Mac) laden und `vfm check` laufen lassen.
