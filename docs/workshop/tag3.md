# Spickzettel Tag 3 (Mi 2.12.): Suche, RAG und Agent

Heute: Embeddings, Re-Ranking, top-k, "Chatte mit deinen Dokumenten" (RAG) und
ein Agent (Hermes, der Recherche-Agent aus Jans Session), der die Pipeline ueber die Schnittstelle `/api` nutzt.

Befehle in der Container-Shell (`docker compose exec app bash`) oder mit dem
Praefix `docker compose exec app vfm ...`.

## Embeddings erstellen

Ein Embedding ist ein Zahlenvektor, der die Bedeutung eines Textabschnitts
(Chunk) beschreibt. Aehnliche Bedeutung = aehnlicher Vektor. So findet die Suche
auch Treffer ohne gleiche Woerter.

```bash
vfm embed                    # berechnet Vektoren fuer alle Chunks ohne Vektor
vfm embed --alle-neu         # alles mit dem aktuellen Modell neu rechnen
vfm status                   # Spalte "mit Embeddings (aktuelles Modell)"
```

Die Embeddings werden **je Modell** gespeichert. Mit einem zweiten Modell
vergleichen (ueberschreibt nichts). Zuerst das Modell holen, auf **deinem
Rechner** (nicht im Container; es ist nicht auf dem USB-Stick, also vorher mit
Internet ziehen, sonst ist die Uebung optional):

```bash
ollama pull qwen3-embedding:0.6b
```

Dann mit dem Modell rechnen und suchen (von aussen, mit `-e`):

```bash
docker compose exec -e EMBED_MODEL=qwen3-embedding:0.6b app vfm embed
docker compose exec -e EMBED_MODEL=qwen3-embedding:0.6b app vfm suche "Wer liefert Lagerdienstleistungen?"
```

(In der Container-Shell geht auch `EMBED_MODEL=qwen3-embedding:0.6b vfm embed`.)

Dauerhaft wechseln: `EMBED_MODEL=...` in der `.env`, dann `docker compose up -d`.

## Suche: Volltext, semantisch, Rerank

```bash
vfm suche "Lagerdienstleistungen" --volltext        # klassisch, braucht das Wort
vfm suche "Wer liefert Lagerdienstleistungen?"      # semantisch + Rerank
vfm suche "Wer liefert Lagerdienstleistungen?" --ohne-rerank
vfm suche "Wer liefert Lagerdienstleistungen?" --top-n 50 --top-k 5
```

- **top-n**: so viele Kandidaten holt die Vektorsuche (breit und grob).
- **Rerank**: ein zweites Modell sortiert diese Kandidaten genauer nach der
  Frage neu. Die Spalte "Vektor-Rang -> Rerank-Rang" zeigt, wer aufsteigt.
- **top-k**: so viele Treffer zeigst du am Ende an.

In der Oberflaeche: Seite "Suche" mit Volltext- und semantischem Modus.

## RAG: mit den Dokumenten chatten

```bash
vfm frage "Wie hoch ist der Vertragswert und wer sind die Vertragsparteien?"
vfm frage "Welche Zahlungen sind vereinbart?" --top-k 5
```

Ablauf: Frage -> semantische Suche + Rerank -> die besten Treffer gehen als
Quellen an das Sprachmodell -> Antwort mit Verweisen wie `[1]`. Die Tabelle
darunter loest `[1]` in Dateiname und Dokument-ID auf. Pruefe immer die
Quelle: Das Modell kann sich verschlucken.

Weitere Analysen mit dem LLM: `vfm analyse` (Zusammenfassung, Kategorie,
Bildbeschreibung). Eigene Kategorien: `config/kategorien.yaml`.

## Hermes-Agent: die Schnittstelle /api

Der Agent spricht ueber HTTP mit der Pipeline. Beschreibung zum Ausprobieren:
http://localhost:8999/docs (Abschnitt "agent"). Ist in der `.env` ein
`API_TOKEN` gesetzt, brauchen alle Aufrufe den Kopf
`Authorization: Bearer <Token>`; ohne `API_TOKEN` geht es ohne.

```bash
# Suche (modus=semantisch oder volltext, top_k 1 bis 50)
curl "http://localhost:8999/api/suche?q=Lagerdienstleistungen&modus=volltext&top_k=3"
curl "http://localhost:8999/api/suche?q=Wer%20liefert%20Lagerdienstleistungen&top_k=3"

# Ein Dokument mit Text, Entitaeten, Analysen
curl http://localhost:8999/api/dokumente/3

# Entitaeten ueber alle Dokumente (optional label=, q=, limit=)
curl "http://localhost:8999/api/entitaeten?label=iban"

# Frage beantworten lassen (RAG)
curl -X POST http://localhost:8999/api/frage \
  -H "Content-Type: application/json" \
  -d '{"frage": "Wie hoch ist der Vertragswert?"}'
```

Mit Token:

```bash
curl -H "Authorization: Bearer MEIN_TOKEN" "http://localhost:8999/api/suche?q=Rechnung&modus=volltext"
```

Fehlercodes: 401 = Token fehlt oder falsch, 409 = noch keine Embeddings
(`vfm embed` ausfuehren), 502 = Modell nicht erreichbar.

Gib dem Agenten die Adresse `http://localhost:8999/openapi.json` (maschinenlesbare
Beschreibung) oder die vier Endpunkte oben, und lass ihn selbst Fragen
beantworten. Laeuft der Agent selbst in Docker, nimm statt `localhost`
die Adresse `host.docker.internal`.

## Uebungsaufgaben

1. Erzeuge die Embeddings und stelle dieselbe Frage mit `--volltext` und
   semantisch. Wann findet nur die semantische Suche etwas?
2. Vergleiche `--ohne-rerank` und mit Rerank. Steigt ein Treffer auf?
   Spiele mit `--top-n` und `--top-k`.
3. Rechne die Embeddings mit einem zweiten Modell und vergleiche die
   Trefferlisten fuer dieselbe Frage.
4. Stelle drei Fragen mit `vfm frage`: eine, die klar im Material steht, eine
   zum Zusammenfuehren mehrerer Dokumente, und eine, die **nicht** im Material
   steht. Wie reagiert das Modell?
5. Rufe `/api/suche` und `/api/dokumente/<id>` per curl auf. Baue mit dem
   Agenten eine Recherche-Frage, die beide Endpunkte nutzt.
