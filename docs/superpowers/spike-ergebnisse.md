# Spike-Ergebnisse (Task 0)

Stand: 2026-11-10. Gemessen auf Apple Silicon (arm64, CPU/MPS-frei, nur CPU-Pfade), Ollama lokal.
Cortecs: **kein API-Key vorhanden** (Ruling R4). Alles, was nur mit einem echten Aufruf pruefbar ist, ist als
"ungeprueft (kein Key)" markiert. Bestaetigt wurde nur: die Modellliste ist ohne Auth lesbar, und die Endpunkte
existieren (Antwort 401 bzw. 405 statt 404).

## Entscheidungen auf einen Blick

| Thema | Entscheidung |
|---|---|
| GliNER | Paket `gliner2`, Modell `fastino/gliner2-base-v1`, **englische Labels** (`person`, `company`, `location`, `amount`, `date`); deutsche Labels gleich gut (24/26), daher Wahl nur nach Konvention |
| Docling offline | `docling-tools models download layout tableformer easyocr -o <dir>`; zusaetzlich Paket `easyocr` installieren; EasyOCR-Gewichte liegen danach im selben Ordner (`EasyOcr/`), kein weiterer Download |
| Whisper | `faster-whisper`, Modell `small`, `compute_type="int8"`, `device="cpu"`, `language="de"`, `beam_size=5`, `vad_filter=True`, `download_root=/models/whisper`; **`av<17` pinnen** |
| Reranker lokal | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (470 MB); Upgrade-Option `BAAI/bge-reranker-v2-m3` (2,1 GB) |
| `CHAT_EXTRA_BODY` (Ollama, qwen3.5:4b) | `{"reasoning_effort": "none"}` |
| Embedding | `bge-m3`, Dimension **1024** (Ollama und Cortecs identisch) |
| Image-Groesse | grob 4 bis 4,5 GB unkomprimiert (siehe unten) |

## Tabelle je Rolle

| Rolle | Ollama (`ollama`-Profil) | Cortecs (`cortecs`-Profil) | `local`-Fallback | Zahlen / Bemerkungen |
|---|---|---|---|---|
| chat | `qwen3.5:4b`, `response_format` json_schema geht, mit `reasoning_effort:"none"` 0,7 s | `qwen3.5-9b` (EUR 0,10/0,15 je 1M Token, ovh/ionos, json_mode) ungeprueft (kein Key); Alternative `mistral-small-2603` | - | Ohne Thinking-Abschaltung: 800 Token verbraucht, `content` leer (Reasoning frisst das Budget), 14,8 s |
| vision | `qwen3-vl:8b` (liest Dokumentbild korrekt); `qwen3.5:4b` las ein A4-Dokument bei 1,5x Rendering NICHT (11,6 s, "keine Infos") | `qwen3.5-9b` oder `qwen3-vl-235b-a22b` (beide Tag Vision), ungeprueft | Docling-OCR | `data:image/jpeg;base64` im `image_url` funktioniert bei beiden Ollama-Modellen; kleines Bild (1200x400) las auch `qwen3.5:4b` richtig (1,7 s). qwen3-vl:8b: 13,8 s mit `reasoning_effort:none`, **4,2 s mit `think:false`** |
| embed | `bge-m3` 1024 Dim, 1,7 s fuer 11 Texte; `qwen3-embedding:0.6b` 1024 Dim, 1,5 s | `bge-m3` (EUR 0,01/1M, ovh/ionos), ungeprueft; Alternative `qwen3-embedding-8b`, `multilingual-e5-large` | `sentence-transformers` nicht noetig | Beide Ollama-Modelle ranken die richtige Passage auf Platz 1. Gleiche Familie und gleiche Dimension auf beiden Profilen, daher Index zwischen Profilen kompatibel |
| rerank | - (Ollama hat keinen Rerank-Endpunkt) | `bge-reranker-v2-m3` (berget, EUR 0,10/1M) oder `qwen3-vl-reranker-8b`, `POST /v1/rerank`, ungeprueft | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` via `sentence-transformers` | Siehe Reranker-Abschnitt |
| transcribe | - | `whisper-large-v3-turbo` (ovh) / `whisper-large-v3`, `POST /v1/audio/transcriptions`, ungeprueft | `faster-whisper small int8` | 17,4 s Audio: .opus 2,3 s, .m4a 1,9 s (CPU, warm) |
| gliner | (immer lokal) | - | `gliner2` + `fastino/gliner2-base-v1` | 24/26 Treffer, 0,3 s fuer 5 Saetze |
| docling | (immer lokal) | - | Docling + EasyOCR de | 9,7 s je Seite (warm), 14,5 s erster Lauf |

## GliNER (Schritt 2)

Fuenf deutsche Saetze, 26 erwartete Entitaeten (Person, Firma, Ort, Betrag, Datum), Schwelle 0,4 (nur `gliner`).

| Paket / Modell | Labels | Treffer | Bemerkung |
|---|---|---|---|
| `gliner` / `urchade/gliner_multi-v2.1` | DE | 24/26 | Rauschen: "Provisionen" als Betrag, "Christian Sewing"/"Peter Lang" als Firma |
| `gliner` / `urchade/gliner_multi-v2.1` | EN | 25/26 | gleiches Rauschen ("Provisionen") |
| `gliner2` / `fastino/gliner2-base-v1` | DE | 24/26 | sauberer, keine Fantasie-Treffer; Verwechslung "Deutsche Bank" fehlt, Betrag bei Satz 2 leer |
| `gliner2` / `fastino/gliner2-base-v1` | EN | 24/26 | identisch zu DE |

Entscheidung: `gliner2` mit `fastino/gliner2-base-v1`, API `GLiNER2.from_pretrained(...).extract_entities(text, labels)`
liefert `{"entities": ...}`-aehnliches Dict je Label. Labelsprache EN (Modell ist englisch trainiert, deutsche
Labels bringen keinen Vorteil). Modellgroesse 816 MB, Ladezeit gemessen 87 s inklusive Download. Hinweis: das Modell
laedt zusaetzlich `microsoft/mdeberta-v3-base` (nur Tokenizer-Dateien, 4 MB) aus dem HF-Hub; fuer Offline-Betrieb
muss dieser Cache mit im Image liegen (`HF_HOME` auf den Modellordner zeigen lassen).
`gliner` (v1) verwarfen wir: 2,2 GB und mehr Rauschen bei gleicher Trefferzahl.

## Docling offline (Schritt 3)

Schritte, exakt:

```bash
uv pip install docling easyocr          # easyocr ist KEINE Docling-Abhaengigkeit; ohne Paket bricht der Download ab
docling-tools models download layout tableformer easyocr -o models/docling   # 21 s, 777 MB
```

Ordner danach: `docling-project--docling-layout-heron` (164 MB), `docling-project--docling-layout-heron-onnx` (163 MB),
`docling-project--docling-models` (342 MB, TableFormer), `EasyOcr/` (108 MB: `craft_mlt_25k.pth`, `english_g2.pth`,
`latin_g2.pth`). Das deutsche Modell ist `latin_g2` und kommt damit schon mit, **kein zusaetzlicher Gewichtedownload**.

Konvertierung offline (verifiziert mit `HF_HUB_OFFLINE=1 HF_HOME=/nonexistent`):

```python
o = PdfPipelineOptions()
o.ocr_options = EasyOcrOptions(lang=["de"], force_full_page_ocr=True, download_enabled=False,
                               model_storage_directory="/models/docling/EasyOcr")
o.artifacts_path = "/models/docling"
o.accelerator_options.device = "cpu"
```

Beachten: `force_full_page_ocr` ist ein Feld von `EasyOcrOptions`, nicht von `PdfPipelineOptions`.
Messung (Scan-PDF, 1 Seite A4, 150 dpi, CPU): 14,5 s (erster Lauf), 9,7 s (zweiter Lauf). Qualitaet: Fliesstext und
Zahlen korrekt (250.000 Euro, 12. Maerz 2024), aber die Titelzeile "Kaufvertrag Nr. 2024-117" ging verloren und
Zeilen wurden zu einem Absatz verschmolzen. Fuer den Workshop akzeptabel, im Hinweistext erwaehnen.

## Whisper (Schritt 4)

`faster-whisper 1.2.1`, `small`, int8, CPU, 17,4 s deutsche Sprachnachricht (macOS `say -v Anna`, per ffmpeg zu .opus
und .m4a). Beide Formate werden gelesen (PyAV, kein ffmpeg-Binary noetig). Transkript praktisch fehlerfrei
("zwoelften Maerz" wurde zu "12. Maerz", "zweitausendfuenfhundert" zu "2.500"), 2,3 s (.opus) bzw. 1,9 s (.m4a).
Modellordner 464 MB. **Stolperstein:** mit `av==19.0.2` (vom Resolver gewaehlt) bricht `transcribe` mit
`TypeError: open() got an unexpected keyword argument 'metadata_errors'` ab; `av<17` (getestet: 16.1.0) loest es.
In `pyproject.toml` `av>=14,<17` pinnen.

## Reranker (Schritt 5)

Deutsche Frage plus 10 Absaetze (3 relevant). Jina v2 wurde NICHT getestet, weil es `trust_remote_code=True` braucht
(Fremdcode-Ausfuehrung); stattdessen `BAAI/bge-reranker-v2-m3`.

| Modell | Groesse | Ladezeit | Rangfolge (Index) | Bemerkung |
|---|---|---|---|---|
| `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | 470 MB | 44 s (inkl. Download) | 0, 7, 6, 2, 4 ... | beide direkten Treffer (0, 7) vorn, Rauschen klar hinten; Scores 10,9 / 5,9 / 3,2 |
| `BAAI/bge-reranker-v2-m3` | 2,1 GB | 138 s (inkl. Download) | 0, 7, 6, 2, 4 ... | gleiche Reihenfolge, Scores 1,0 / 0,78 / 0,05 (schaerfere Trennung), Vorhersage 0,4 s |

Beide stellen Passage 6 ("gegruendet 1998") vor Passage 2 ("Zahlung an Herrn Schmidt"); das ist vertretbar. Entscheidung
lokal: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (Groesse), konfigurierbar ueber Settings, `bge-reranker-v2-m3` als Option
(passt zum Cortecs-Modell gleichen Namens).

## Ollama (Schritt 6)

- `response_format: {"type":"json_schema","json_schema":{"name":..., "schema":..., "strict":true}}` an `/v1/chat/completions` wird von qwen3.5:4b eingehalten, sobald Thinking aus ist.
- Thinking abschalten (qwen3.5:4b, Test mit gleichem Prompt):
  - `{"reasoning_effort":"none"}`: wirkt, 0,7 s, saubere JSON-Antwort.
  - `{"think": false}` im Body: **wirkt nicht** (11,5 s, `content` leer).
  - `{"chat_template_kwargs":{"enable_thinking":false}}`: **wirkt nicht**.
  => `CHAT_EXTRA_BODY={"reasoning_effort":"none"}` im Ollama-Profil. Gilt fuer Cortecs ebenfalls (laut Doku
  `reasoning_effort:"none"`).
- `qwen3-vl:8b` (Vision): `reasoning_effort:"none"` laesst Reasoning laufen (13,8 s), `{"think": false}` ist schneller (4,2 s).
  Empfehlung: eigenes `VISION_EXTRA_BODY={"think": false}` fuer das Ollama-Profil, falls `qwen3-vl:8b` gewaehlt wird.
  Fuer Ollama-Vision ist `qwen3-vl:8b` die Wahl (`qwen3.5:4b` scheiterte am A4-Dokumentbild).
- Embeddings: `bge-m3` und `qwen3-embedding:0.6b` je 1024 Dimensionen. Entscheidung `bge-m3` (identisch mit Cortecs).
  pgvector-Spalte: `Vector(1024)`.

## Cortecs (Schritt 7), ohne Key

Basis-URL `https://api.cortecs.ai/v1` bestaetigt. `GET /v1/models` ist **ohne Auth** lesbar (105 Eintraege; Embedding-,
Rerank- und Transkriptionsmodelle erscheinen erst mit Filter, z. B. `GET /v1/models?tag=Embedding|Rerank|Transcription`).

| Endpunkt | Existiert | Echt-Aufruf | Modelle (aus Modellliste) |
|---|---|---|---|
| `GET /models` | ja (200 ohne Auth) | ja | siehe oben |
| `POST /chat/completions` | ja (405 bei GET) | ungeprueft (kein Key) | `qwen3.5-9b`, `mistral-small-2603`, `gpt-oss-120b`, ... alle mit `json_mode` |
| Bild-Input (chat) | laut Doku "Image Inputs" | ungeprueft (kein Key) | Tag Vision: `qwen3.5-9b`, `qwen3-vl-235b-a22b`, `gemma-4-26b-a4b-it`, ... |
| `POST /embeddings` | ja (405) | ungeprueft (kein Key) | `bge-m3`, `qwen3-embedding-8b`, `multilingual-e5-large`, `bge-multilingual-gemma2` |
| `POST /audio/transcriptions` | ja (401) | ungeprueft (kein Key) | `whisper-large-v3`, `whisper-large-v3-turbo`, `faster-whisper-large-v3`, `voxtral-*-transcribe` |
| `POST /rerank` | ja (401) | ungeprueft (kein Key) | `bge-reranker-v2-m3`, `qwen3-vl-reranker-8b` |

Aus der Doku (docs.cortecs.ai, nicht per Aufruf verifiziert): Auth per `Authorization: Bearer`. Rerank-Body
`{model, query, documents[], top_n}` -> `results[{index, relevance_score}]`; Transkription `multipart/form-data`
(`file`, `model`, `language`); Embeddings `{model, input, encoding_format}`; Thinking aus mit `reasoning_effort:"none"`
(bei nicht abschaltbaren Modellen niedrigster Level, bei Modellen ohne Einstellung ignoriert). Zusatzparameter
(`preference`, `eu_native`, `allowed_providers`) nicht in Standard-Clients noetig. Nachzuholen, sobald ein Key da ist:
je ein echter Aufruf pro Endpunkt, besonders json_schema (nur `json_mode` ist laut Liste ausgewiesen) und Bild-Input.

## Image-Groesse (Schritt 8, grob)

| Posten | Groesse |
|---|---|
| venv (macOS-arm64 mit Torch, easyocr, docling, gliner2, gliner, faster-whisper, ST) | 1,5 GB (Linux: Torch **CPU-only** Index nutzen, sonst +2 bis 3 GB CUDA; `gliner` v1 entfaellt) |
| gliner2-base-v1 | 0,8 GB |
| Docling-Artefakte inkl. EasyOCR | 0,78 GB |
| Whisper small | 0,46 GB |
| Reranker mMiniLM | 0,47 GB (bge-reranker-v2-m3: 2,1 GB) |
| Summe | ca. 4 GB, mit bge-reranker ca. 5,6 GB |

## Hinweise fuer spaetere Tasks

- Settings-Felder: `chat_extra_body` (JSON), optional `vision_extra_body`, `embed_dim=1024`, `whisper_pfad`, Docling-`artifacts_path`.
- `profile/cortecs.env` mit obigen Modellnamen als Annahme, Kommentar "ungeprueft (kein Key)".
- `av<17` in den Abhaengigkeiten pinnen.
