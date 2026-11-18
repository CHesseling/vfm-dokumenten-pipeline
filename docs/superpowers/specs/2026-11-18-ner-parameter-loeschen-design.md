# NER-Parameter und Löschen in der GUI – Design (kurz)

Stand: 18.11.2026

## Zweck

Teilnehmende sollen im Workshop selbst ausprobieren, was sich bei der Entitätserkennung
ändert, wenn sie **eigene Kategorien (Labels)** und die **GliNER-Schwelle** setzen – in der
GUI und in der CLI. Außerdem sollen sie Ergebnisse eines Dokuments (Entitäten, Embeddings)
gezielt löschen können, um Schritte noch einmal sauber zu sehen.

## Ziele / Nicht-Ziele

- Ziel: frei benannte Labels (z. B. `aktenzeichen`, `behörde`) für GliNER und LLM, Schwelle
  für GliNER, je Lauf einstellbar; sichtbar, mit welchen Parametern die aktuellen Treffer
  entstanden sind.
- Ziel: Entitäten (je Methode) und Embeddings (aktuelles Modell / alle) je Dokument löschen.
- Nicht-Ziel: mehrere Ergebnisvarianten derselben Methode nebeneinander (Variante B, ggf. später).
- Anti-Ziel: globale Einstellungen in der GUI – Teilnehmende würden sich gegenseitig die Werte
  verstellen.

## Ansätze

- **A – Parameter pro Lauf, letztes Ergebnis gilt (gewählt).** Formular und CLI nehmen Labels
  und Schwelle; ein Lauf ersetzt die Treffer dieser Methode; Parameter stehen im `Lauf`.
  Keine Schemaänderung, bis zum Workshop sicher machbar.
- B – Varianten nebeneinander (Treffer bekommen eine Variante, Vergleich mit Spalte je
  Variante). Schönerer Vergleich, aber Migration und Umbau überall, wo nach Methode gruppiert
  wird. Verworfen wegen Aufwand/Zeit.
- C – globale Einstellungsseite. Verworfen (siehe Anti-Ziel).

## Entscheidungen

**Label-Eingabe** (GUI-Textfeld und `vfm ner --labels`): kommagetrennt, je Eintrag
`name` oder `name=englischer Begriff`, z. B. `person, aktenzeichen=file number, behörde`.
- Die acht bekannten Labels (`LABELS`) bekommen ihren GliNER-Begriff automatisch
  (`GLINER_LABELS`, für iban/telefon/email bisher keiner – dann geht der Name selbst ans Modell).
- Eigenes Label ohne `=`: der deutsche Name geht direkt an GliNER (schwächer – das ist im
  Workshop gewollt sichtbar).
- LLM: Beschreibung = englischer Begriff falls angegeben, sonst Name (`ERKLAERUNG.get(l, l)`
  bleibt für bekannte Labels).
- Muster: arbeitet nur mit bekannten Labels, eigene werden ignoriert.
- Gespeichertes Label = der Name (ohne englischen Teil). Eigene Labels: `normalisiert = None`.
- Vorbelegung im Formular: die acht Standard-Labels. Leeres Feld = Standard.

**Schwelle**: neues Setting `gliner_schwelle` (Default 0.5, per `.env` änderbar), im Formular
als Zahl/Regler, CLI `--schwelle`. Gilt nur für GliNER.

**Protokoll und Anzeige**: Labels (mit englischem Teil) und Schwelle landen in
`Lauf.roh_output`. Die Dokumentseite zeigt je Methode über den Treffern, aus welchem Lauf sie
stammen, z. B. „gliner · Schwelle 0.3 · Labels: person, aktenzeichen“.

**Markierung**: eigene Labels bekommen eine neutrale Einheitsfarbe (Klasse z. B. `ent-eigen`),
Label steht im `title`.

**Löschen** (Dokumentseite, mit `confirm()`-Abfrage):
- „Entitäten löschen“ je Methode und „alle“ – betrifft die aktive Extraktion (das, was die
  Seite zeigt).
- „Embeddings löschen“ – nur aktuelles `EMBED_MODEL` oder alle Modelle, für alle Chunks des
  Dokuments.
- Nach dem Löschen gilt das Ergebnis als **fehlend**: „NER für alle“ / „Embeddings erzeugen“
  auf der Status-Seite füllen es mit Standardwerten wieder auf. (Heute zählt ein erfolgreicher
  `Lauf` als „vorhanden“ – das muss das Löschen berücksichtigen.)
- Löschen wird als `Lauf` protokolliert (Schritt z. B. `loeschen:ner:gliner`, `loeschen:embed`).

**Doku**: `docs/workshop/tag2.md` (eigene Labels, Schwelle, Löschen), `AGENTS.md`
(NER-Abschnitt: Labels nicht mehr fest), `.env.example`/Profile falls nötig.

## Dem Umsetzenden überlassen

- Validierung der Label-Eingabe (sinnvolle Grenzen für Anzahl/Länge, erlaubte Zeichen).
- Wie „gelöscht = fehlend“ technisch umgesetzt wird.
- Ob Löschen auch in der CLI angeboten wird (nicht verlangt).
- Gestaltung der Formularelemente im bestehenden Stil (vanilla JS, Jinja2).
