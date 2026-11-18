# CLEF als zweiter Klassifikator – Design (kurz)

Stand: 18.11.2026

## Zweck

Teilnehmende vergleichen Qualität und Tempo zweier Klassifikationsverfahren: das
bisherige LLM (Chat-Modell nennt Kategorie, Begründung, Sicherheit) gegen den
Classifier CLEF (Cloudflare `clef-flash`, liefert eine Wahrscheinlichkeit je
Kategorie). Sie sehen beide Ergebnisse nebeneinander – in der GUI und in der CLI.

## Ziele / Nicht-Ziele

- Ziel: CLEF über Cortecs (Decisions-API), gleiche Frage und gleiche Kategorien wie beim
  LLM, gleicher Text; Ergebnis und Dauer je Verfahren sichtbar nebeneinander.
- Ziel: Frage und Kategorien stehen in `config/kategorien.yaml` und lassen sich im
  laufenden Container ändern.
- Nicht-Ziel: Auswertung (Übereinstimmungsquote, Trefferquote, „richtige Kategorie“).
- Nicht-Ziel: CLEF lokal (Ollama) oder Frage/Kategorien in der GUI bearbeiten.

## Ansätze

- **A – eigene Analyse-Art `klassifikation_clef` neben `klassifikation` (gewählt).**
  Getrennte Ergebnisse und Läufe (Dauer je Verfahren), einzeln neu rechenbar.
- B – Umschalter LLM *oder* CLEF: kein Nebeneinander, verworfen.
- C – beide Ergebnisse in einem Datensatz: kein getrenntes Neurechnen, Dauer nicht sauber
  zuordenbar, verworfen.

## Entscheidungen

**Cortecs Decisions-API** (Beta): `POST {CLASSIFY_BASE_URL}/decisions`, Modell
`clef-flash:latest`, Format „Decisions“:
`{"model", "input": <Text>, "questions": [{"type": "choice", "name": "kategorie",
"instructions": <Frage>, "choices": [{"value": <Name>, "description": <Beschreibung>}]}]}`.
Antwort `answers[0]`: `choice`, `confidence`, `probabilities: [{value, probability}]`;
Typ `refusal` gilt als Fehler.

**Einstellungen** (Rolle `classify`): `CLASSIFY_BASE_URL=https://api.cortecs.ai/v1`,
`CLASSIFY_MODEL=clef-flash:latest`, `CLASSIFY_API_KEY` (leer = `CORTECS_API_KEY`, und zwar
unabhängig vom Provider – so lässt sich ein lokales LLM mit CLEF bei Cortecs vergleichen).
Ohne Schlüssel ist CLEF aus: „Analyse für alle“, `vfm pipeline` und die Dokumentseite lassen
es still weg; `vfm analyse --art klassifikation_clef` meldet den fehlenden Schlüssel.
`vfm check`/Status-Seite zeigen die Rolle (aus, oder API erreichbar).

**Frage und Kategorien**: `config/kategorien.yaml` bekommt die Form
`{frage: <Text>, kategorien: [{name, beschreibung}, ...]}`; die bisherige reine Liste bleibt
gültig (Standardfrage). Standardfrage = bisheriger Prompt-Anfang
„Ordne das Dokument genau einer der folgenden Kategorien zu:“. Das LLM bekommt die Frage
statt des festen Satzes. `docker-compose.yml` bindet `./config` read-only nach `/app/config`
ein (bisher wirkten Änderungen an der Datei im Container nicht).

**Gleicher Text**: beide Verfahren bekommen die ersten `MAX_ZEICHEN` (12 000) Zeichen der
aktiven Extraktion.

**Ergebnis CLEF** (`Analyse.ergebnis`): `kategorie`, `sicherheit` (= confidence),
`wahrscheinlichkeiten` (Name → Wahrscheinlichkeit). Dauer steht wie bei allen Analysen im
`Lauf` (`analyse:klassifikation_clef`, `dauer_ms`).

**Anzeige**:
- Dokumentseite: Tabelle „Klassifikation: LLM und CLEF“ mit Verfahren, Modell, Kategorie,
  Sicherheit, Dauer; darunter LLM-Begründung und CLEF-Wahrscheinlichkeiten (absteigend).
- Neue Seite „Klassifikation“ (Navigation): oben Frage und Kategorien, darunter je Dokument
  LLM-Kategorie (Sicherheit, Dauer) und CLEF-Kategorie (Sicherheit, Dauer).
- CLI: `vfm klassifikation [--dokument ID]` druckt dieselbe Tabelle.

**Doku**: `docs/workshop/tag3.md`, README, AGENTS.md, `.env.example`.

## Umsetzung (Reihenfolge, je mit Tests)

1. Kategorien-Datei mit Frage (`lade_klassifikation`), LLM nutzt die Frage, compose-Mount.
2. Rolle `classify`: Settings, `DecisionsClient` (respx-Tests), Factory, `vfm check`.
3. Analyse-Art `klassifikation_clef` im Analyse-Ablauf (aus ohne Schlüssel), CLI `--art`.
4. Anzeige: Dokumentseite, Seite „Klassifikation“, `vfm klassifikation`; Doku.

## Dem Umsetzenden überlassen

- Genaues Layout der Tabellen im bestehenden Stil.
- Umgang mit CLEF-Antworten, deren `choice` keiner Kategorie entspricht (Fallback wie beim
  LLM: „Sonstiges“, Rohwert behalten).
