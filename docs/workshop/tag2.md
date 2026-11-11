# Spickzettel Tag 2 (Di 1.12.): Datenbank und Entitaeten

Heute: Blick in die Datenbank mit SQL, Named Entity Recognition (NER) mit
GliNER2, Muster fuer IBANs, Telefonnummern und mehr.

Befehle in der Container-Shell (`docker compose exec app bash`) oder mit dem
Praefix `docker compose exec app vfm ...`.

## Blick in die Datenbank (SQL)

SQL ist **nur lesend** und genau eine Anweisung pro Aufruf. Du kannst nichts
kaputtmachen. In der Oberflaeche unter "SQL" gibt es Beispielabfragen zum
Anklicken; im Terminal:

```bash
vfm sql "SELECT typ, count(*) AS anzahl FROM dokument GROUP BY typ ORDER BY anzahl DESC"
vfm sql "SELECT id, dateiname, typ, groesse FROM dokument ORDER BY groesse DESC LIMIT 10"
vfm sql "SELECT metadaten->>'absender' AS absender, count(*) AS anzahl FROM dokument WHERE typ = 'eml' GROUP BY absender ORDER BY anzahl DESC"
vfm sql "SELECT d.id, d.dateiname, left(c.text, 200) AS ausschnitt FROM chunk c JOIN textextraktion t ON t.id = c.textextraktion_id JOIN dokument d ON d.id = t.dokument_id WHERE c.tsv @@ websearch_to_tsquery('german', 'Rechnung') LIMIT 20"
vfm sql "SELECT d.dateiname, a.art, a.ergebnis FROM \"analyse\" a JOIN dokument d ON d.id = a.dokument_id ORDER BY d.dateiname"
vfm sql "SELECT d.id, d.dateiname, d.typ FROM dokument d WHERE NOT EXISTS (SELECT 1 FROM textextraktion t WHERE t.dokument_id = d.id) ORDER BY d.id"
```

Die wichtigsten Tabellen:

| Tabelle | Inhalt |
|---|---|
| `dokument` | eine Zeile je Datei (id, dateiname, typ, groesse, metadaten, parent_id fuer Mail-Anhaenge) |
| `textextraktion` | Text je Methode (dokument_id, methode, text, dauer_ms, ist_aktiv) |
| `chunk` | Textabschnitte fuer die Suche (textextraktion_id, position, text) |
| `entitaet` | erkannte Entitaeten (textextraktion_id, methode, label, text, normalisiert) |
| `embedding` | Vektoren je Chunk und Modell |
| `"analyse"` | Zusammenfassungen, Kategorien, Bildbeschreibungen |
| `lauf` | Protokoll jedes Verarbeitungsschritts (Dauer, Fehler) |

Achtung: `analyse` ist in SQL ein reserviertes Wort. Setze den Tabellennamen in
Anfuehrungszeichen: `SELECT * FROM "analyse"`. Mehr Spalten siehst du mit
`vfm sql "SELECT * FROM entitaet LIMIT 5"`.

## Entitaeten erkennen (NER)

Drei Methoden, die du vergleichen sollst:

| Methode | Was sie findet | Staerke | Schwaeche |
|---|---|---|---|
| `muster` | IBAN, Telefon, E-Mail, Geldbetrag, Datum (feste Regeln, Pruefsummen) | exakt, sehr schnell | nur diese Formate |
| `gliner` | Person, Organisation, Ort, Datum, Geldbetrag (kleines KI-Modell, lokal) | schnell, versteht Kontext | kann sich irren, z. B. eine IBAN als Betrag |
| `llm` | alles, was du per Label nennst (Sprachmodell) | flexibel | langsam |

```bash
vfm ner                                        # Standard: gliner + muster fuer alle Dokumente
vfm ner --methode muster                       # nur Regeln
vfm ner --methode muster --labels iban,telefon
vfm ner --methode llm --dokument <ID>          # LLM nur fuer ein Dokument
vfm ner --methode alle --vergleich --dokument <ID>   # drei Methoden nebeneinander
```

`--vergleich` zeigt eine Tabelle: welche Methode hat welche Entitaet gefunden?
Die Spalte "normalisiert" macht Schreibweisen vergleichbar (eine IBAN mit und
ohne Leerzeichen zaehlt als dieselbe).

In der Oberflaeche: Seite "Entitaeten" (Gruppen ueber alle Dokumente, Filter
nach Art) und im Dokumentdetail der Text mit markierten Entitaeten.

```bash
vfm sql "SELECT label, text, count(*) AS anzahl FROM entitaet GROUP BY label, text ORDER BY anzahl DESC LIMIT 30"
vfm sql "SELECT DISTINCT d.id, d.dateiname, e.text AS iban FROM entitaet e JOIN textextraktion t ON t.id = e.textextraktion_id JOIN dokument d ON d.id = t.dokument_id WHERE e.label = 'iban' ORDER BY d.id"
```

## Uebungsaufgaben

1. Zaehle mit SQL die Dokumente je Typ. Welche Dokumente haben noch keinen Text?
2. Lass `vfm ner --methode muster` laufen. Welche IBANs und Telefonnummern
   stehen in deinen Dokumenten? In wie vielen Dokumenten kommt jede vor?
3. Waehle ein Dokument mit Personen und Firmen und vergleiche
   `vfm ner --methode alle --vergleich --dokument <ID>`. Wo sind sich die Methoden
   einig, wo nicht? Wer hat Fantasie-Treffer?
4. Schreibe eine eigene SQL-Abfrage: Welche Personen kommen in mehr als einem
   Dokument vor? (Tipp: `SELECT e.text, count(DISTINCT t.dokument_id) FROM entitaet e JOIN textextraktion t ON t.id = e.textextraktion_id WHERE e.label = 'person' GROUP BY e.text HAVING count(DISTINCT t.dokument_id) > 1`)
5. Finde mit der Seite "Entitaeten" eine Organisation und rufe alle Dokumente
   auf, in denen sie vorkommt.
