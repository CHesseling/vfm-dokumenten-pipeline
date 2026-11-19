# Workshop-Pipeline: Dokumente mit KI auswerten

Begleitmaterial zum vfm-Datenseminar (30.11.-2.12.2026, Claus Hesseling und
Jan Eggers).

Die Pipeline liest Rechercheunterlagen ein (PDFs, Scans, Mails, Sprachnachrichten,
Videos, Fotos, Word/Excel/PowerPoint, Textdateien), holt den Text heraus, erkennt Personen, Organisationen,
IBANs und Telefonnummern, macht alles durchsuchbar und beantwortet Fragen mit
Quellenangabe ("Chatte mit deinen Dokumenten"). Alles laeuft auf deinem
eigenen Rechner in Docker; die Sprachmodelle laufen lokal mit Ollama (oder
optional bei einem Cloud-Anbieter).

Die Spickzettel fuer die drei Tage liegen in [docs/workshop/](docs/workshop/):
[Tag 1](docs/workshop/tag1.md) - [Tag 2](docs/workshop/tag2.md) -
[Tag 3](docs/workshop/tag3.md).

## Ablauf der Pipeline

```
Ingest  ->  NER  ->  Embed  ->  Analyze  ->  Display
Text holen  Entitaeten  Vektoren   Zusammenfassung,  Weboberflaeche,
(OCR, Audio) erkennen   + Suche    Kategorie         SQL, API
```

Jeder Schritt hat einen eigenen Befehl (`vfm ingest`, `vfm ner`, `vfm embed`,
`vfm analyse`). Mit `vfm pipeline <Ordner>` laufen alle in einem Zug.

## Einrichten

Du brauchst: Docker (Docker Desktop oder colima) oder Podman, mindestens 8 GB
Arbeitsspeicher fuer Docker bzw. die Podman-Machine, ca. 15 GB freien Platz und
Ollama (https://ollama.com). Ohne Ollama geht es mit einem Cortecs-Schluessel,
siehe "Ohne lokale Modelle arbeiten".

**Podman statt Docker:** Alles funktioniert gleich. Die Skripte erkennen selbst, ob
Docker oder Podman laeuft (erzwingen: `VFM_ENGINE=podman`). Bei den Befehlen
unten steht dann `podman compose` statt `docker compose`. Auf dem Mac vorher
`podman machine start`; `podman compose` braucht `docker-compose` oder
`podman-compose` (z. B. `brew install docker-compose`).

### Schnellstart: ein Befehl (online)

Vorher installieren und starten: Docker Desktop (https://www.docker.com/products/docker-desktop/)
und Ollama (https://ollama.com/download). Dann im Terminal:

- Mac/Linux:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/CHesseling/vfm-dokumenten-pipeline/main/scripts/start.sh | bash
  ```
- Windows (PowerShell):
  ```powershell
  irm https://raw.githubusercontent.com/CHesseling/vfm-dokumenten-pipeline/main/scripts/start.ps1 | iex
  ```

Der Befehl legt das Projekt in `~/vfm-pipeline` (Windows: `%USERPROFILE%\vfm-pipeline`) ab,
laedt die Ollama-Modelle und das fertige App-Image (zusammen bis zu 20 GB, am besten
vorher im heimischen WLAN), startet alles und oeffnet http://localhost:8999.
Erneut ausfuehren aktualisiert auf den neuesten Stand; deine `.env` und `material/` bleiben.

Statt das fertige Image zu laden, kann das Skript es auch lokal bauen (dauert
10-20 Minuten): `curl ... | bash -s -- --build` bzw. unter Windows vorher
`$env:VFM_BUILD = "1"` setzen.

### Weg A: mit dem USB-Stick (ohne Internet)

1. Stecke den Stick ein und starte Docker (und Ollama).
2. Oeffne ein Terminal im Stick-Ordner und fuehre das Einspiel-Skript aus:
   - Mac/Linux: `./einspielen.sh` (falls der Stick nicht ausfuehrbar ist: `bash einspielen.sh`)
   - Windows (PowerShell): `powershell -ExecutionPolicy Bypass -File .\einspielen.ps1`
3. Das Skript laedt die Docker-Images, kopiert die Ollama-Modelle (es fragt vorher
   nach) und entpackt das Projekt nach `~/vfm-pipeline` (Windows: `%USERPROFILE%\vfm-pipeline`).
4. Weiter mit "Starten" unten. Details stehen in der `ANLEITUNG.md` auf dem Stick.

### Weg B: online

```bash
git clone <Repository-Adresse> vfm-pipeline
cd vfm-pipeline
ollama pull qwen3.5:4b
ollama pull qwen3-vl:8b
ollama pull bge-m3
cp .env.example .env
```

(Die Modelle sind zusammen mehrere GB gross; `ollama pull` erst im WLAN mit
Zeit starten.) Stelle in der Ollama-App die Kontextlaenge auf mindestens 16k
(Einstellungen) oder starte Ollama mit `OLLAMA_CONTEXT_LENGTH=16384`; sonst
schneidet Ollama lange Dokumente still ab. Danach "Starten". Beim ersten `docker compose up -d` wird das Image gebaut: das
dauert mehrere Minuten, braucht Internet und laedt mehrere GB.

### Starten

```bash
docker compose up -d
docker compose exec app vfm check
```

`vfm check` prueft jede Modell-Rolle (Chat, Vision, Embedding, Rerank,
Transkription). Alle Zeilen sollten **OK** zeigen. Beim ersten Start dauert es
ein paar Sekunden, bis die Datenbank bereit ist.

Die Oberflaeche erreichst du unter **http://localhost:8999**.

### Terminal im Browser

Unter **http://localhost:7681** (Link "Terminal" oben in der Oberflaeche) laeuft
eine Shell im App-Container: `vfm ...`, `alembic`, die Datenbank per
`psql "${DATABASE_URL/+psycopg/}"`, Dateien unter `/data` und `/material` und
die Einstellungen in `/app/.env` (dieselbe Datei wie `.env` im Projektordner,
mit `nano .env` bearbeitbar). Die Shell laeuft als
`appuser`; mit `sudo` geht alles als root (z. B. `sudo apt-get install ...`,
bleibt nur bis zum Neustart des Containers).

Einstellungen in der `.env`: `TERMINAL=aus` schaltet es ab, `TERMINAL_PORT`
aendert den Port, `TERMINAL_PASS` (und `TERMINAL_USER`, Standard `admin`) setzt
einen Login. Wie die Oberflaeche ist das Terminal nur lokal erreichbar
(`TERMINAL_BIND=127.0.0.1`). Wer es auf einem Server freigibt
(`TERMINAL_BIND=0.0.0.0`), muss `TERMINAL_PASS` setzen: Das Terminal kann alles.

## Material einlesen

Lege deine Unterlagen in den Ordner `material` im Projektordner (er liegt im
Container unter `/material`). Dann:

```bash
docker compose exec app vfm ingest /material
docker compose exec app vfm status
```

Das Material bleibt auf deinem Rechner; es ist nicht im Repository.
Alternativ kannst du Dateien in der Oberflaeche unter "Upload" hochladen.

## Befehlsuebersicht

Alle Befehle laufen im Container: `docker compose exec app vfm <Befehl>`.

| Befehl | Was er tut | Beispiel |
|---|---|---|
| `vfm check` | Prueft, ob alle Modelle erreichbar sind | `vfm check` |
| `vfm status` | Zeigt je Dokumenttyp, wie weit die Verarbeitung ist | `vfm status` |
| `vfm ingest <Pfad>` | Liest Datei oder Ordner ein und holt den Text heraus. `--methode schnell\|docling\|vision\|alle` waehlt bei PDFs die Textmethode | `vfm ingest /material --methode alle` |
| `vfm text <ID>` | Zeigt den aktiven Text; `--vergleich` stellt die Methoden nebeneinander, `--aktiv <Methode>` waehlt eine aus | `vfm text 4 --vergleich` |
| `vfm sql "<Abfrage>"` | Fuehrt eine lesende SQL-Abfrage aus (`--limit` begrenzt die Zeilen) | `vfm sql "SELECT typ, count(*) FROM dokument GROUP BY typ"` |
| `vfm ner` | Erkennt Entitaeten. `--methode gliner\|muster\|llm\|alle`, `--dokument <ID>`, `--labels person,iban`, `--vergleich`, `--alle-neu` (sonst werden vorhandene Ergebnisse uebersprungen) | `vfm ner --methode alle --vergleich --dokument 3` |
| `vfm embed` | Berechnet Vektoren fuer alle Textabschnitte; `--alle-neu` rechnet neu | `vfm embed` |
| `vfm suche "<Anfrage>"` | Semantische Suche; Rerank = ein zweites Modell sortiert die Kandidaten genauer nach der Frage neu; `--volltext`, `--ohne-rerank`, `--top-n`, `--top-k` | `vfm suche "Wer liefert Lagerdienstleistungen?"` |
| `vfm frage "<Frage>"` | Antwort mit Quellenangaben (RAG); `--top-k` | `vfm frage "Wie hoch ist der Vertragswert?"` |
| `vfm analyse` | Zusammenfassung, Kategorie, Bildbeschreibung. `--art zusammenfassung\|klassifikation\|bildbeschreibung\|alle`, `--dokument <ID>`, `--alle-neu` (sonst werden vorhandene Analysen uebersprungen) | `vfm analyse --art zusammenfassung` |
| `vfm pipeline <Ordner>` | Einlesen, Entitaeten (GliNER + Muster), Embeddings und Analysen in einem Zug | `vfm pipeline /material` |

Mit `vfm --provider cortecs <Befehl>` (oder `-p`) wechselst du den Anbieter
nur fuer diesen einen Aufruf. `vfm <Befehl> --help` zeigt alle Optionen.

Hinweis fuer SQL: Die Tabelle `analyse` muss in Anfuehrungszeichen stehen (`"analyse"`, reserviertes Wort).

In der Weboberflaeche gibt es dieselben Funktionen: Dokumente (mit Detailseite
und Methodenvergleich), Suche, Entitaeten, SQL, Status, Upload.

## Klassifikation: LLM und CLEF im Vergleich

Neben dem LLM gibt es einen zweiten Klassifikator: CLEF (Cloudflare `clef-flash`)
ueber die Decisions-API von Cortecs. Er liefert je Kategorie eine Wahrscheinlichkeit.
Er ist optional und laeuft nur mit einem Cortecs-Schluessel in der `.env`
(`CORTECS_API_KEY=...`), auch wenn alles andere lokal mit Ollama laeuft.

Frage und Kategorien stehen fuer beide Verfahren in `config/kategorien.yaml`.
`vfm analyse --art klassifikation_clef` rechnet CLEF, `vfm klassifikation` zeigt
LLM und CLEF nebeneinander (Kategorie, Sicherheit, Dauer); in der Oberflaeche die
Seite "Klassifikation". Optional ueberschreibbar: `CLASSIFY_MODEL`
(Standard `clef-flash:latest`), `CLASSIFY_BASE_URL`, `CLASSIFY_API_KEY`.
Die Decisions-API ist bei Cortecs noch Beta.

## Agenten anbinden (z. B. Hermes)

Eine Erklaerseite mit allen Endpunkten, Parametern und curl-Beispielen gibt es in der
Oberflaeche unter **API** (`/api-hilfe`).

Ein Agent wie Hermes nutzt die Pipeline ueber die HTTP-Schnittstelle `/api`:
Suche (`/api/suche`), Frage mit Quellen (`/api/frage`), ein Dokument
(`/api/dokumente/{id}`) und Entitaeten (`/api/entitaeten`). Die Beschreibungen
sind bewusst ausfuehrlich und auf Deutsch, damit der Agent sie versteht. Gib ihm
die maschinenlesbare Beschreibung `http://localhost:8999/openapi.json`;
zum Ausprobieren im Browser: http://localhost:8999/docs.

Welche Adresse der Agent nimmt, haengt davon ab, wo er laeuft:

| Agent laeuft ... | Adresse |
|---|---|
| direkt auf demselben Rechner | `http://localhost:8999/api` |
| in einem eigenen Docker-Container | `http://host.docker.internal:8999/api` |
| im Compose-Netz der Pipeline (`docker network connect vfm-pipeline_default <agent-container>`) | `http://app:8000/api` |
| auf einem anderen Rechner | `http://<IP-des-Rechners>:8999/api`, dazu in der `.env` `APP_BIND=0.0.0.0` |

Eine eigene "Bridge" braucht es nicht, der Agent ruft die Schnittstelle direkt auf.
Ist der Agent von anderen Rechnern aus erreichbar oder die Pipeline nicht nur an
`127.0.0.1` gebunden, setze in der `.env` ein `API_TOKEN`; ohne Token ist `/api` offen.
Der Agent schickt es dann als Kopf `Authorization: Bearer <Token>` mit.

Beispielaufrufe und Fehlercodes stehen im Spickzettel [Tag 3](docs/workshop/tag3.md).

## Anbieter wechseln (Ollama oder Cortecs)

Standard ist `PROVIDER=ollama` (alles lokal). Fuer den Cloud-Anbieter Cortecs
(EU, OpenAI-kompatibel) setzt du in der `.env`:

```
PROVIDER=cortecs
CORTECS_API_KEY=dein-schluessel
```

und startest neu: `docker compose up -d`. Danach `vfm check`. Hinweis: Die
Cortecs-Werte (Modellnamen, Adressen) in `profile/cortecs.env` sind noch **nicht
geprueft**. Wenn `vfm check` Fehler zeigt, bitte melden.

Einzelne Werte (z. B. `CHAT_MODEL`) kannst du in der `.env` ueberschreiben; sie
haben Vorrang vor den Profilen in `profile/`. Umgebungsvariablen (z. B.
`docker compose exec -e CHAT_MODEL=... app vfm ...`) schlagen wiederum die `.env`. Das gilt auch fuer `-p cortecs`: Der
Schalter waehlt nur das Profil, Werte aus `.env` oder der Umgebung schlagen es
weiterhin.

### Ohne lokale Modelle arbeiten

Kein Ollama installiert, zu wenig Arbeitsspeicher oder die Modelle passen nicht
auf die Platte? Dann uebernimmt Cortecs Chat, Bildbeschreibung und Embeddings.
Du brauchst dafuer nur einen Cortecs-Schluessel. Texterkennung (Docling),
Transkription (Whisper), GliNER und Rerank laufen weiter im Container, die
Modelle dafuer stecken im Image.

Umgestellt wird von Hand in der Datei `.env` im Projektordner
(`~/vfm-pipeline/.env`, Windows: `%USERPROFILE%\vfm-pipeline\.env`). Dieselbe
Datei siehst du im Browser-Terminal als `/app/.env`; du kannst sie dort oder auf
dem Rechner bearbeiten.

1. Datei oeffnen:
   - im Browser-Terminal (Link "Terminal" in der Oberflaeche): `nano .env`
   - oder auf dem Rechner, Mac/Linux: `cd ~/vfm-pipeline && nano .env`,
     Windows: `notepad $env:USERPROFILE\vfm-pipeline\.env`
2. Die Zeile `PROVIDER=ollama` aendern in `PROVIDER=cortecs`.
3. Hinter `CORTECS_API_KEY=` deinen Schluessel eintragen, ohne Leerzeichen und
   ohne Anfuehrungszeichen: `CORTECS_API_KEY=sk-...`
4. Speichern. In nano: `Strg+O`, `Enter`, dann `Strg+X` zum Beenden.
5. Pruefen: `vfm check` (im Browser-Terminal) bzw. `docker compose exec app vfm check`.
   Oben steht jetzt `Provider-Profil: cortecs`, chat, vision und embed zeigen die
   Cortecs-Modelle (z. B. `qwen3.5-9b`, `bge-m3`) und sollten **OK** melden.
   Alle `vfm`-Befehle nutzen die Aenderung sofort.
6. Die Oberflaeche liest die `.env` nur beim Start. Auf dem Rechner:
   `docker compose restart app`.

Die Startskripte (`start.sh`/`start.ps1`) laufen auch ohne Ollama durch; sie
weisen nur darauf hin. Zurueck zu den lokalen Modellen: `PROVIDER=ollama`, dann
wieder Schritt 5 und 6. Wer vorher schon Embeddings erzeugt hat, laesst nach
jedem Wechsel einmal `vfm embed` laufen (siehe unten).

Hinweise zur `.env` im Browser-Terminal:
- "Permission denied" beim Speichern (Linux, je nach Benutzer-Zuordnung):
  `sudo nano .env`.
- Mit nano bearbeiten, nicht mit Werkzeugen, die die Datei ersetzen statt
  ueberschreiben (`sed -i`, manche vim-Einstellungen): Der Container saehe sonst
  weiter die alte Fassung.
- Die Terminal-Schalter (`TERMINAL...`) und Ports (`APP_PORT`, `APP_BIND` usw.)
  wirken erst nach `docker compose up -d` auf dem Rechner.
- Nur ausprobieren, ohne die Datei zu aendern:
  `CORTECS_API_KEY=sk-... vfm -p cortecs check`.

Wichtig: Embeddings werden je Modell gespeichert. Wechselst du das
Embedding-Modell, laeuft `vfm embed` einmal neu; die Suche nutzt immer das
aktuelle Modell.

## Fehlerbehebung

**"Ollama nicht erreichbar" / `vfm check` zeigt Fehler bei chat, vision oder embed**
- Ollama-App starten (Menueleiste bzw. Taskleiste) oder im Terminal `ollama serve`.
- Pruefen: `ollama list` muss `qwen3.5:4b`, `qwen3-vl:8b` und `bge-m3` zeigen.
- Der Container erreicht Ollama ueber `host.docker.internal:11434`. Auf Linux
  funktioniert das durch den Eintrag in `docker-compose.yml`; Ollama muss dort
  auf allen Schnittstellen lauschen (`OLLAMA_HOST=0.0.0.0`). Das gilt auch fuer
  rootless Podman unter Linux. Mit der Podman-Machine auf dem Mac reicht das
  normale Ollama.
- Alternative: Ollama im Container: `docker compose --profile ollama up -d`, die
  Modelle dort mit `docker compose exec ollama ollama pull qwen3.5:4b` (usw.)
  ziehen und in der `.env` die drei `*_BASE_URL` auf `http://ollama:11434/v1`
  setzen.

**Lange Dokumente werden nur teilweise ausgewertet (Zusammenfassung ignoriert das Ende)**
- Ollama schneidet Eingaben still am Kontextfenster ab. Kontextlaenge in der
  Ollama-App auf mindestens 16k stellen (Einstellungen) bzw. Ollama mit
  `OLLAMA_CONTEXT_LENGTH=16384` starten. Im Container (`--profile ollama`) ist das
  bereits gesetzt.

**Der Container bricht ab oder ist extrem langsam (zu wenig Arbeitsspeicher)**
- Docker Desktop: Einstellungen, Resources, Memory auf mindestens 8 GB.
- colima: `colima stop && colima start --memory 8` (oder mehr).
- Podman (Mac/Windows): `podman machine stop && podman machine set --memory 8192 && podman machine start`.

**Podman: "permission denied" auf `/material` oder `/app/config` (Fedora/RHEL)**
- SELinux: Die Bind-Mounts tragen in `docker-compose.yml` bereits `:z`. Wer eigene
  Mounts ergaenzt, braucht dort ebenfalls `:z`.

**Windows**
- Docker Desktop mit WSL2-Backend installieren und starten.
- Skripte blockiert? PowerShell mit `powershell -ExecutionPolicy Bypass -File .\einspielen.ps1` starten.
- Das Einspiel-Skript wurde noch nicht auf einem echten Windows-Rechner getestet.
  Wenn es hakt, melde dich - Weg B funktioniert auch unter Windows.

**Auf einem Server erreichbar machen**
- Standardmaessig ist die Oberflaeche nur lokal (127.0.0.1) erreichbar. Auf einem Server
  `APP_BIND=0.0.0.0` und `API_TOKEN=...` in der `.env` setzen, dazu `SQL_READONLY_URL`
  (die SQL-Seite hat keinen Fallback auf die Haupt-Datenbank).

**Port 8999 ist belegt**
- In `docker-compose.yml` die Zeile `"${APP_BIND:-127.0.0.1}:8999:8000"` aendern, z. B. auf
  `"${APP_BIND:-127.0.0.1}:9001:8000"`, dann `docker compose up -d` und die neue Adresse im Browser nutzen.

**Der erste Docling-Lauf dauert lange**
- Docling (OCR fuer Scans) braucht beim ersten Mal ein paar Sekunden zum
  Laden und danach pro Seite etwa 10 bis 15 Sekunden. Das ist normal.
  Die Vision-Methode ist nochmal langsamer.

**Befehle im Terminal erscheinen nicht im Fortschrittsbalken der Oberflaeche**
- Der Fortschritt in der Weboberflaeche zeigt nur Laeufe, die dort gestartet
  wurden (Upload, Status-Seite). Ein `vfm ...` im Terminal zeigt seinen
  eigenen Balken im Terminal; das Ergebnis siehst du danach in der Oberflaeche.

**Alles zuruecksetzen**
- `docker compose down -v` loescht Datenbank und eingelesene Dateien (Achtung,
  endgueltig). Dein Ordner `material` bleibt unberuehrt.

## Bekannte Grenzen

- Cortecs-Modellnamen und -Adressen sind noch nicht mit einem echten Schluessel geprueft.
- Das PowerShell-Einspielskript ist nicht auf einem echten Windows-Rechner getestet.
- Das amd64-Image (Intel/Windows/Linux) wurde gebaut, aber noch nicht auf dem
  Zielserver ausprobiert; arm64 (Apple Silicon) ist getestet.
- Alte Office-Formate (`.doc`, `.xls`, `.ppt`) werden nicht gelesen; vorher als
  `.docx`/`.xlsx`/`.pptx` oder PDF speichern. Bei Videos wird nur die Tonspur transkribiert.
- HTML-Originale werden aus Sicherheitsgruenden nur zum Download angeboten, nicht angezeigt.

## Fuer Entwickler

Struktur, Konzepte, Tests und Deployment stehen in [AGENTS.md](AGENTS.md).
