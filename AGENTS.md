# AGENTS.md

Struktur- und Betriebs-Referenz fuer dieses Repo. Fachlicher Hintergrund und
Architekturentscheidungen: `docs/superpowers/specs/2026-11-10-workshop-pipeline-design.md`.
Messwerte/Modellwahl: `docs/superpowers/spike-ergebnisse.md`. Implementierungsplan
(historisch): `docs/superpowers/plans/2026-11-10-workshop-pipeline.md`.
Teilnehmer-Doku: `README.md` und `docs/workshop/tag{1,2,3}.md` (nicht fuer Entwickler geschrieben, bei
Verhaltensaenderungen aber mitpflegen).

## Zweck

Workshop-Pipeline fuers vfm-Datenseminar (30.11.-2.12.2026): liest Rechercheunterlagen
(PDF, Mail, Audio, Bild, Text) ein, extrahiert Text (mehrere Methoden pro Dokument),
erkennt Entitaeten (Muster, GliNER2, LLM), erzeugt Embeddings, beantwortet Fragen per RAG
und stellt alles ueber CLI (`vfm`), FastAPI-GUI und eine Agent-API (`/api`) bereit.
Code, Bezeichner, UI-Texte und Fehlermeldungen sind deutsch (Bezeichner mit ae/oe/ue,
UI-Texte mit Umlauten). Material liegt nie im Repo (`material/`, `data/` gitignored).

## Verzeichnisstruktur

```
app/
  main.py               FastAPI-App-Factory (create_app), Router, Lifespan
  cli.py                 Typer-CLI "vfm" (check, status, ingest, text, sql, ner, embed,
                         suche, frage, analyse, pipeline), globale Option --provider
  config.py              Settings (pydantic-settings), lade_settings(provider),
                         api_key_fuer(rolle), vision_effektiv()
  db.py                  SQLModel-Engine/Session (Singleton), get_session
  enums.py               Enums (DokumentTyp, ExtraktionsMethode, NerMethode, LaufStatus ...)
  progress.py            In-Memory-Fortschritt fuer Hintergrund-Laeufe (Prozess-global)
  statistik.py           Zaehler fuer "vfm status" und Status-Seite
  logging_config.py      logging-Setup (LOG_LEVEL)

  providers/             Alles, was Modelle anspricht (Rollen chat/vision/embed/rerank/transcribe)
    factory.py             chat_client / vision_client / embedding_client / reranker /
                           transkribierer aus Settings
    llm_client.py          LLMClient (chat_json, Bildvariante), ProviderFehler, Retries,
                           hartes Gesamt-Zeitbudget
    embeddings.py          EmbeddingClient (OpenAI-kompatibel, Batches)
    rerank.py              LokalerReranker (CrossEncoder) / ApiReranker
    transcribe.py          LokalerTranskribierer (faster-whisper) / ApiTranskribierer
    check.py               pruefe_rollen: Grundlage von "vfm check" und Status-Seite
    url.py                 ohne_zugangsdaten(): userinfo aus URLs entfernen

  ingest/                Datei -> Dokument + TextExtraktion(en)
    ablauf.py              ingest_datei / ingest_ordner, Methodenwahl je Dateityp
    speichern.py           dokument_speichern (SHA-Dedup), extraktion_speichern,
                           aktive_extraktion_waehlen (flushen nur, Commit macht der Aufrufer)
    dateitypen.py          erkenne_typ
    pdf.py / pdf_render.py pdf_schnell (pypdfium2), pdf_docling (OCR, offline), pdf_vision
    eml.py / eml_parse.py  Mail -> Text + Anhaenge (Kind-Dokumente), Metadaten
    audio.py bild.py text.py  Transkription, Bild-OCR + EXIF, Textdateien
    chunking.py            chunken(): Chunks nur fuer die AKTIVE Extraktion

  ner/                   Entitaeten
    muster.py              Regex/Pruefsummen (iban, telefon, email, geldbetrag, datum),
                           normalisiere(label, text)
    gliner.py              GliNER2 lokal, englische Modell-Labels -> deutsche Labels
    llm_ner.py             LLM-Extraktion mit Offset-Suche (Wortgrenzen)
    labels.py              freie Labels ("name=englischer Begriff") parsen, Schwelle pruefen
    treffer.py             Treffer-Datentyp
    ablauf.py              ner_starten (Methoden, Labels, Vergleich)

  embed/                 RAG
    index.py               Embeddings je Modell berechnen (nur fehlende / --alle-neu)
    suche.py               semantische Suche: Vektor (top_n) -> Rerank -> top_k
    volltext.py            Postgres-Volltext (tsvector, 'german')
    rag.py                 antwort_erzeugen: Antwort mit Fussnoten [n]
    treffer.py             Treffer-Datentypen

  analyse/               LLM-Analysen (Zusammenfassung, Klassifikation, Bildbeschreibung)
    ablauf.py              analyse_starten; hierarchische Zusammenfassung (max. 3 Ebenen)
    kategorien.py          liest config/kategorien.yaml

  sql/                   abfrage.py (read-only SQL ausfuehren), beispiele.py (BEISPIELE fuer GUI/Doku)
  api/routes.py          /api/suche, /api/dokumente/{id}, /api/entitaeten, /api/frage (Bearer-Token optional)
  models/                SQLModel-Tabellen: dokument.py (Dokument, TextExtraktion, Chunk, Embedding,
                         Entitaet), auswertung.py (Analyse, Lauf), _typen.py (Spaltentypen)
  web/                   routes_{dokumente,suche,entitaeten,sql,status,upload}.py, vorlagen.py,
                         templates/ (Jinja2, vanilla JS, Polling alle 2 s)

alembic/versions/0001_basis.py   Basis-Schema inkl. pgvector, tsvector und Rolle vfm_leser
config/kategorien.yaml           Kategorien fuer die Klassifikation
profile/{ollama,cortecs}.env     Provider-Profile (Werte je Rolle)
.env.example                     PROVIDER, DATABASE_URL, SQL_READONLY_URL, CORTECS_API_KEY, API_TOKEN
scripts/                         image_bauen.sh, usb_paket_bauen.sh, einspielen.sh/.ps1,
                                 modelle_laden.py (Image-Build), fixtures_erzeugen.py (Mini-Satz)
tests/                           spiegelt app/ 1:1, plus tests/fixtures/ (mini/ = Mini-Satz)
docs/workshop/                   Spickzettel Tag 1-3
docs/superpowers/                Spec, Plan, Spike-Ergebnisse
```

## Zentrale Konzepte

- **Rollen und Profile**: Rollen sind `chat`, `vision`, `embed`, `rerank`, `transcribe`.
  `lade_settings(provider)` liest `profile/<provider>.env` und dann `.env` (`.env`
  gewinnt; `--provider` und `PROVIDER` waehlen das Profil). `api_key_fuer(rolle)`
  nimmt den rollen-eigenen Key, bei `provider == cortecs` sonst `CORTECS_API_KEY`
  (Fallback). Vision faellt ueber `vision_effektiv()` auf Chat zurueck. Rerank und
  Transkription gibt es als Backend `local` (Standard, Ollama kann beides nicht) oder `api`.
  Cortecs-Werte in `profile/cortecs.env` sind **ungeprueft** (beim Spike war kein Key vorhanden).
  `chat_extra_body` / `vision_extra_body` schalten Thinking ab (modellabhaengig, siehe
  Spike). Leere Variable in `.env` heisst "nicht gesetzt" (nur Felder ohne Default).
- **Aktive Extraktion**: Ein Dokument hat mehrere `TextExtraktion` (schnell, docling,
  vision, eml, whisper ...); genau eine ist `ist_aktiv`. NER, Chunks, Embeddings,
  Suche und Analyse arbeiten nur mit der aktiven. **Chunks entstehen nur fuer die aktive
  Extraktion**; `vfm text --aktiv` / GUI wechselt sie. Standard-PDF-Methode ist
  `schnell`; unter `MINDEST_TEXT_SCHNELL` Zeichen kommt Docling automatisch dazu.
  Fehlgeschlagene Methoden werden als `Lauf` mit Status FEHLER protokolliert und
  blockieren die anderen nicht.
- **Embeddings je Modell, ohne feste Dimension**: Tabelle `embedding` (chunk_id, modell,
  vektor) mit unbeschraenkter `vector`-Spalte, daher beliebige Modelle nebeneinander;
  kein Vektor-Index, exakte Suche mit `cosine_distance`. Suche und Status nutzen nur
  Embeddings des aktuellen `EMBED_MODEL`. Ein `vector_dims`-Guard filtert Zeilen
  mit abweichender Dimension, bevor verglichen wird. Modellwechsel => `vfm embed` rechnet nur das Fehlende.
- **Schrittweiser Ablauf**: Ingest -> NER -> Embed -> Analyse sind getrennte Befehle
  (Teilnehmende sollen jeden Schritt einzeln sehen). `vfm pipeline <Pfad>` fuehrt alle in
  einem Zug aus (NER dort: GliNER + Muster) und nennt bei `ProviderFehler` die abgebrochene
  Stufe samt Nachhol-Befehlen. Jeder Schritt schreibt `Lauf`-Zeilen (Dauer, Fehler, Modell).
- **NER mit drei Methoden**: `muster` (exakt), `gliner` (GliNER2, Modell-Labels englisch),
  `llm`; `--vergleich` zeigt sie nebeneinander. Alle Methoden schreiben `normalisiert` ueber
  dieselbe Funktion `normalisiere(label, text)` (None fuer person/organisation/ort); sonst zerfiele dieselbe IBAN je Methode
  in Gruppen. Telefon-Treffer, die Datum/Geldbetrag
  ueberlappen, werden verworfen (phonenumbers erkennt "03.03.2024" als Nummer). Bekannte Eigenheit: GliNER labelt IBANs gelegentlich als `geldbetrag`.
  **Labels sind frei** (GUI-Formular und `vfm ner --labels`, `app/ner/labels.py`): `name` oder
  `name=englischer Begriff`; GliNER nutzt den Begriff, sonst `GLINER_LABELS`, sonst den Namen
  (bekannte Labels ohne GliNER-Begriff wie iban/telefon/email ueberspringt GliNER). Schwelle per
  `--schwelle`/Formular, Default `GLINER_SCHWELLE` (0.5). Labels und Schwelle stehen in
  `Lauf.roh_output` und werden auf der Dokumentseite angezeigt. Ein Lauf ersetzt die Treffer der
  Methode (keine Varianten nebeneinander).
- **Loeschen je Dokument** (GUI): Entitaeten je Methode (`entitaeten_loeschen`, aktive Extraktion)
  und Embeddings (`embeddings_loeschen`, aktuelles Modell oder alle). Protokolliert als Lauf
  `loeschen:ner:<methode>` bzw. `loeschen:embed`; `_ner_vorhanden` zaehlt nur ERFOLG-Laeufe nach dem
  letzten Loeschen, damit "NER fuer alle" Geloeschtes wieder auffuellt.
- **SQL read-only**: `app/sql/abfrage.py` erlaubt genau **eine** Anweisung, laeuft in einer
  read-only Transaktion ueber `SQL_READONLY_URL` und die Postgres-Rolle `vfm_leser`
  (Migration 0001: nur SELECT, `statement_timeout` 10 s). `SQL_READONLY_URL` MUSS in der
  Workshop-`.env` gesetzt sein; der App-DB-User darf kein Superuser sein, sonst koennten
  `pg_read_file`/`pg_terminate_backend` genutzt werden (nur die Rolle schuetzt davor).
  Tabelle `analyse` ist in SQL reserviert und muss als `"analyse"` zitiert werden.
- **ProviderFehler + Zugangsdaten**: Alle Modellaufrufe uebersetzen Netz-/HTTP-Fehler in
  `ProviderFehler` mit lesbarer deutscher Meldung. `ProviderFehler` bereinigt die `base_url`
  zentral (userinfo/Keys raus), damit nichts davon in GUI, Lauf-Tabelle oder CLI
  landet. Ungemappte `httpx.HTTPStatusError` koennen noch die volle URL enthalten (bekannt).
  Zeitueberschreitungen und 4xx (ausser 408/429) werden nicht wiederholt.
- **Hintergrund-Laeufe und Fortschritt**: Upload, Ordner-Import und die Aktionen der
  Status-Seite (NER, Embed, Analyse) laufen in Threads mit eigener DB-Session;
  `app/progress.py` haelt den Stand **nur im Prozess** (kein Multi-Worker, geht bei
  Neustart verloren), die GUI pollt alle 2 s, `Abbrechen` setzt ein Flag. CLI-Laeufe sind
  davon getrennt (eigener Balken im Terminal). Einzelne kurze LLM-Calls (RAG-Antwort,
  Check) bleiben synchron im Request.
- **Offline / Modelle**: Im Image ist `HF_HOME=/models/hf`, `HF_HUB_OFFLINE=1`,
  `TRANSFORMERS_OFFLINE=1`. `scripts/modelle_laden.py --ziel /models` laedt beim Build
  Reranker, GliNER2 (+ Tokenizer `microsoft/mdeberta-v3-base`), Whisper `small`
  (`/models/whisper`, Setting `whisper_pfad`) und Docling/EasyOCR (`/models/docling`,
  `docling_artifacts_pfad`). Lokale Modelle werden erst bei Erstbenutzung geladen
  (Modul-Cache), nie beim Import. Ein anderes als das vorgeladene Modell scheitert offline.
- **Dedup/Ordner-Import**: Dateien werden per SHA-256 dedupliziert; Ordner-Import
  (`ingest_ordner`) verschiebt nichts (Material wird von vielen wiederverwendet, SHA-Dedup reicht). Mail-Anhaenge werden Kind-Dokumente
  (`parent_id`); Inline-Bilder mit Content-ID zaehlen nicht (Signatur-/Logo-Bilder).
- **Agent-API**: `/api/*` mit optionalem `Authorization: Bearer <API_TOKEN>`
  (leer = offen; Vergleich per `hmac.compare_digest`). OpenAPI-Beschreibungen sind
  deutsch und bewusst ausfuehrlich (der Agent liest sie). 409 = keine Embeddings, 502 = Provider.

## Tests

```
uv run pytest                          # ganze Suite (ohne Modelltests)
uv run pytest tests/ingest/            # ein Modul
uv run pytest -m modelle               # echte-Modelle-Tests und E2E (siehe unten)
```

Braucht Postgres+pgvector (Default `TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/vfm_test`):

```
docker run -d --name vfm-testdb -p 5433:5432 -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=vfm_test pgvector/pgvector:pg16
```

`tests/conftest.py` legt Tabellen einmal pro Session an und leert sie pro Test.
HTTP-Modellaufrufe werden mit respx gemockt; lokale Modelle (GliNER, Whisper, Docling,
CrossEncoder) hinter Funktionen, die per monkeypatch ersetzt werden. Test-Dateien
spiegeln `app/` 1:1 (`app/ingest/pdf.py` <-> `tests/ingest/test_pdf.py`).

Marker `modelle` (per `addopts = "-m 'not modelle'"` ausgeschlossen): `tests/test_e2e.py`
laeuft den Mini-Satz (`tests/fixtures/mini`) durch. Voraussetzungen: Ollama auf
`localhost:11434` mit `qwen3.5:4b`, `qwen3-vl:8b`, `bge-m3`; Modellordner
`spike/models/{hf,whisper,docling}` (Spike-Download); Mini-Fixtures vorhanden
(`uv run python scripts/fixtures_erzeugen.py`; Audio ist nicht byte-reproduzierbar).
Fehlt etwas, wird der Test uebersprungen.

## Lokale Entwicklung

```
uv sync                                # Dependencies
cp .env.example .env
ollama pull qwen3.5:4b
ollama pull qwen3-vl:8b
ollama pull bge-m3
docker compose up -d                   # db + app (Migrationen laufen via entrypoint.sh)
docker compose exec app vfm check
```

GUI auf Port 8999 (`docker-compose.yml`), standardmaessig nur an 127.0.0.1 gebunden (`APP_BIND`, `OLLAMA_BIND`). Migrationen im laufenden Container erzeugen
und zurueckkopieren (DATABASE_URL zeigt auf `db`, nicht `localhost`):

```
docker compose exec app alembic revision --autogenerate -m "..."
docker cp <container>:/app/alembic/versions/<datei>.py alembic/versions/
```

Autogenerierte Dateien pruefen (`import sqlmodel`, `nullable`, pgvector-Typen).

## Deployment und USB-Paket

Zielserver: x86_64/amd64, **kein Registry-/Internet-Zugriff beim Build**; Entwicklung
laeuft auf Apple Silicon (arm64). Images werden deshalb lokal gebaut, als tar exportiert
und per `docker load` eingespielt - nie `docker compose build` auf dem Server.

```
scripts/image_bauen.sh amd64|arm64     # baut vfm-pipeline:latest-<arch> -> dist/vfm-pipeline-<arch>.tar.gz
                                       # ("vfm-pipeline:latest" nur bei nativer Architektur)
scripts/usb_paket_bauen.sh ZIEL [--ohne-ollama-modelle]   # Offline-Paket
scripts/usb_paket_bauen.sh --nur-modelle-pruefen          # Trockenlauf der Modell-Dateien
```

Das USB-Paket enthaelt `images/` (App, pgvector, Ollama je amd64+arm64), `ollama-modelle/`
(Manifeste+Blobs der Modelle aus `profile/ollama.env`), `vfm-pipeline-repo.tar.gz`
(`git archive HEAD`), `einspielen.sh`/`.ps1` und `ANLEITUNG.md` (Text steht im Skript
`usb_paket_bauen.sh`, dort pflegen). Der Stick braucht exFAT (Dateien > 4 GB). Voll ca. 20 GB.
Aenderungen am Modellsatz: `modelle_laden.py`, `profile/ollama.env` UND die Modellnamen in der
ANLEITUNG (dort hart kodiert) abgleichen.

Hinweise:
- `docker save --platform linux/<arch>` braucht Docker >= 27 und bei **colima** den
  containerd-Image-Store; ohne das exportiert der Befehl die falsche/alle Architekturen.
  Danach Architektur per `docker image inspect <image> --format '{{.Architecture}}'` pruefen.
- Server-Container-User: UID/GID per `APP_UID`/`APP_GID` in der Server-`.env` (Build-Arg UND
  `user:` in `docker-compose.yml`; auf dem Server aktuell 1001, Default 1000). Ein **bereits
  angelegtes** Volume `daten` behaelt die alte Besitzer-UID: Besitzer anpassen
  (`docker run --rm -v <projekt>_daten:/data alpine chown -R 1001:1001 /data`) oder das Volume
  neu anlegen (`docker compose down -v`, loescht Daten).
- Auf dem Server `APP_BIND=0.0.0.0` UND `API_TOKEN` setzen (Default ist 127.0.0.1; ohne Token ist `/api` offen).
- Auf dem Server MUSS `SQL_READONLY_URL` gesetzt sein (siehe SQL read-only). Es gibt keinen Fallback auf `DATABASE_URL`: ohne die Variable meldet die SQL-Seite/`vfm sql` einen Fehler.
- amd64-Image: nur gebaut und per Architektur-Inspektion geprueft, nicht auf dem Server gelaufen.
  `einspielen.ps1` ist nie mit echtem PowerShell gelaufen.

**Fremd-Images (Postgres/pgvector, Ollama) und der kaputte Proxy**: `docker compose up -d`
pullt auf dem Server jedes noch nicht vorhandene Image. `usb_paket_bauen.sh` zieht sie
deshalb je Architektur (`pull_arch`) und sichert sie als tar. Bei Handarbeit NICHT blind auf
die gemeldete Architektur vertrauen, wenn das Tag hier schon in anderer Architektur
gepullt war - der Cache kann `--platform` ignorieren:

```bash
docker image inspect <image>:<tag> --format '{{.Architecture}}/{{.Os}}'
docker buildx imagetools inspect <image>:<tag>      # Digests je Plattform
docker rmi -f <image>:<tag>
docker pull <image>@sha256:<digest-der-zielarchitektur>
docker tag <image>@sha256:<digest> <image>:<tag>
docker save --platform linux/<arch> <image>:<tag> | gzip > dist/<name>.tar.gz
```

Danach lokal wieder auf die native Architektur zuruecksetzen (gleiches Digest-Muster),
sonst laeuft die Dev-Umgebung unter Emulation (`usb_paket_bauen.sh` macht das selbst).

## Bekannte offene Punkte

Cortecs ungeprueft; keine Indizes auf `chunk/entitaet.textextraktion_id`; Fortschritt nur
in-process; fehlgeschlagene Extraktionsmethoden werden bei jedem Lauf erneut versucht;
`vfm check` kann bei toten Endpunkten lange blockieren (serielle Pruefung, grosses Zeitbudget);
Upload liest Dateien komplett in den Speicher.
