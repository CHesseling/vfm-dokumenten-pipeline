# Spickzettel Tag 1 (Mo 30.11.): Einlesen und Texterkennung

Heute: Datensatz kennenlernen, Pipeline-Ueberblick, Docker starten, Dokumente
einlesen und die Texterkennungs-Methoden vergleichen.

## So gibst du Befehle ein

Oeffne im Projektordner eine Shell im Container. Danach beginnt jeder Befehl
einfach mit `vfm`:

```bash
docker compose exec app bash
```

(Raus kommst du mit `exit`.) Ohne Shell geht auch: `docker compose exec app vfm <Befehl>`.
Dein Material liegt im Container unter `/material`.
Wo `<ID>` steht, setzt du die Dokument-Nummer ein, ohne spitze Klammern (z. B. `vfm text 4`).

## Pipeline im Ueberblick

Ingest (Text holen) -> NER (Entitaeten) -> Embed (Vektoren) -> Analyze
(Zusammenfassung) -> Display (Oberflaeche, SQL, API). Heute: Ingest.

## Starten und pruefen

```bash
docker compose up -d
docker compose exec app vfm check     # alle Zeilen sollten OK zeigen
```

Oberflaeche: http://localhost:8999

## Dokumente einlesen

```bash
vfm ingest /material                  # ganzer Ordner, Standardmethode
vfm status                            # wie weit ist jeder Dokumenttyp?
```

Was passiert je Dateityp: PDF liefert Text direkt oder per OCR, Mails werden
zerlegt (Anhaenge werden eigene Dokumente), Audio wird transkribiert (Whisper),
Bilder werden vom Vision-Modell gelesen, Textdateien direkt uebernommen.
Dasselbe Dokument zweimal einzulesen ist harmlos (wird erkannt: "bekannt").

## PDFs: drei Methoden vergleichen

| Methode | Idee | Tempo | Gut fuer |
|---|---|---|---|
| `schnell` | Textebene des PDFs auslesen | Sekundenbruchteile | PDFs mit echtem Text |
| `docling` | Layout- und OCR-Erkennung (lokal) | ca. 10-20 s je Seite | Scans, Tabellen |
| `vision` | Seitenbild an das Vision-Modell | ca. 30-60 s je Seite | schwierige Scans, Handschriftnahes |

Standard ist `schnell`; findet es fast keinen Text (z. B. bei Scans), kommt
`docling` automatisch dazu.

```bash
vfm ingest /material --methode alle            # alle drei Methoden fuer alle PDFs
vfm ingest /material/scan.pdf --methode docling
vfm text <ID> --vergleich                      # Methoden nebeneinander (Zeichen, Dauer, Anfang)
vfm text <ID>                                  # aktiven Text ganz anzeigen
vfm text <ID> --aktiv vision                   # diese Methode zum "aktiven" Text machen
```

Die **ID** siehst du in der Oberflaeche unter "Dokumente" oder mit:

```bash
vfm sql "SELECT id, dateiname, typ FROM dokument ORDER BY id"
```

In der Oberflaeche: Dokument anklicken, dort stehen die Methoden mit Text und
Dauer, und du kannst den aktiven Text umschalten. Alle spaeteren Schritte
(Entitaeten, Suche, Analyse) arbeiten mit dem **aktiven** Text.

## Uebungsaufgaben

1. Lies deinen Ordner ein und schau mit `vfm status`, welche Dokumenttypen
   vorkommen. Welcher Typ ist am haeufigsten?
2. Suche ein gescanntes PDF und vergleiche mit `vfm text <ID> --vergleich`
   die Methoden. Welche liefert den besten Text? Welche ist am schnellsten?
3. Setze die beste Methode mit `--aktiv` als aktiv und pruefe in der
   Oberflaeche (Dokumentdetail), ob sich der Text geaendert hat.
4. Lade eine einzelne Datei ueber "Upload" in der Oberflaeche hoch und
   beobachte den Fortschrittsbalken.
5. Finde ein Dokument, dessen Text leer oder offensichtlich falsch ist. Was
   koennte die Ursache sein (schlechter Scan, Handschrift, Sprache)?

## Wenn etwas hakt

Siehe "Fehlerbehebung" in der [README](../../README.md).
