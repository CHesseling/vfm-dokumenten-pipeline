# Workshop-Pipeline: Dokumente mit KI auswerten

Begleitmaterial zum vfm-Datenseminar (30.11.-2.12.2026, Claus Hesseling und
Jan Eggers).

Die Pipeline liest Rechercheunterlagen ein (PDFs, Scans, Mails, Sprachnachrichten,
Fotos, Textdateien), holt den Text heraus, erkennt Personen, Organisationen,
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

Du brauchst: Docker (Docker Desktop oder colima), mindestens 8 GB Arbeitsspeicher
fuer Docker, ca. 15 GB freien Platz und Ollama (https://ollama.com).

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
Zeit starten.) Danach "Starten". Beim ersten `docker compose up -d` wird das Image gebaut: das
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
| `vfm ner` | Erkennt Entitaeten. `--methode gliner\|muster\|llm\|alle`, `--dokument <ID>`, `--labels person,iban`, `--vergleich` | `vfm ner --methode alle --vergleich --dokument 3` |
| `vfm embed` | Berechnet Vektoren fuer alle Textabschnitte; `--alle-neu` rechnet neu | `vfm embed` |
| `vfm suche "<Anfrage>"` | Semantische Suche; Rerank = ein zweites Modell sortiert die Kandidaten genauer nach der Frage neu; `--volltext`, `--ohne-rerank`, `--top-n`, `--top-k` | `vfm suche "Wer liefert Lagerdienstleistungen?"` |
| `vfm frage "<Frage>"` | Antwort mit Quellenangaben (RAG); `--top-k` | `vfm frage "Wie hoch ist der Vertragswert?"` |
| `vfm analyse` | Zusammenfassung, Kategorie, Bildbeschreibung. `--art zusammenfassung\|klassifikation\|bildbeschreibung\|alle`, `--dokument <ID>` | `vfm analyse --art zusammenfassung` |
| `vfm pipeline <Ordner>` | Einlesen, Entitaeten (GliNER + Muster), Embeddings und Analysen in einem Zug | `vfm pipeline /material` |

Mit `vfm --provider cortecs <Befehl>` (oder `-p`) wechselst du den Anbieter
nur fuer diesen einen Aufruf. `vfm <Befehl> --help` zeigt alle Optionen.

Hinweis fuer SQL: Die Tabelle `analyse` muss in Anfuehrungszeichen stehen (`"analyse"`, reserviertes Wort).

In der Weboberflaeche gibt es dieselben Funktionen: Dokumente (mit Detailseite
und Methodenvergleich), Suche, Entitaeten, SQL, Status, Upload.

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
haben Vorrang vor den Profilen in `profile/`.

Wichtig: Embeddings werden je Modell gespeichert. Wechselst du das
Embedding-Modell, laeuft `vfm embed` einmal neu; die Suche nutzt immer das
aktuelle Modell.

## Fehlerbehebung

**"Ollama nicht erreichbar" / `vfm check` zeigt Fehler bei chat, vision oder embed**
- Ollama-App starten (Menueleiste bzw. Taskleiste) oder im Terminal `ollama serve`.
- Pruefen: `ollama list` muss `qwen3.5:4b`, `qwen3-vl:8b` und `bge-m3` zeigen.
- Der Container erreicht Ollama ueber `host.docker.internal:11434`. Auf Linux
  funktioniert das durch den Eintrag in `docker-compose.yml`; Ollama muss dort
  auf allen Schnittstellen lauschen (`OLLAMA_HOST=0.0.0.0`).
- Alternative: Ollama im Container: `docker compose --profile ollama up -d`, die
  Modelle dort mit `docker compose exec ollama ollama pull qwen3.5:4b` (usw.)
  ziehen und in der `.env` die drei `*_BASE_URL` auf `http://ollama:11434/v1`
  setzen.

**Der Container bricht ab oder ist extrem langsam (zu wenig Arbeitsspeicher)**
- Docker Desktop: Einstellungen, Resources, Memory auf mindestens 8 GB.
- colima: `colima stop && colima start --memory 8` (oder mehr).

**Windows**
- Docker Desktop mit WSL2-Backend installieren und starten.
- Skripte blockiert? PowerShell mit `powershell -ExecutionPolicy Bypass -File .\einspielen.ps1` starten.
- Das Einspiel-Skript wurde noch nicht auf einem echten Windows-Rechner getestet.
  Wenn es hakt, melde dich - Weg B funktioniert auch unter Windows.

**Port 8999 ist belegt**
- In `docker-compose.yml` die Zeile `"8999:8000"` aendern, z. B. auf `"9001:8000"`,
  dann `docker compose up -d` und die neue Adresse im Browser nutzen.

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
- Video wird nicht unterstuetzt (nur PDF, Mail, Audio, Bild, Text).

## Fuer Entwickler

Struktur, Konzepte, Tests und Deployment stehen in [AGENTS.md](AGENTS.md).
