"""Beispielabfragen fuer die SQL-Seite (Titel, SQL)."""

BEISPIELE: list[tuple[str, str]] = [
    (
        "Dokumente je Typ",
        "SELECT typ, count(*) AS anzahl\nFROM dokument\nGROUP BY typ\nORDER BY anzahl DESC",
    ),
    (
        "Größte Dokumente",
        "SELECT id, dateiname, typ, groesse\nFROM dokument\nORDER BY groesse DESC\nLIMIT 10",
    ),
    (
        "Mails nach Absender",
        "SELECT metadaten->>'absender' AS absender, count(*) AS anzahl\n"
        "FROM dokument\nWHERE typ = 'eml'\nGROUP BY absender\nORDER BY anzahl DESC",
    ),
    (
        "Häufigste Entitäten je Label",
        "SELECT label, text, count(*) AS anzahl\nFROM entitaet\n"
        "GROUP BY label, text\nORDER BY anzahl DESC\nLIMIT 30",
    ),
    (
        "Dokumente mit IBAN",
        "SELECT DISTINCT d.id, d.dateiname, e.text AS iban\n"
        "FROM entitaet e\nJOIN textextraktion t ON t.id = e.textextraktion_id\n"
        "JOIN dokument d ON d.id = t.dokument_id\nWHERE e.label = 'iban'\nORDER BY d.id",
    ),
    (
        "Volltextsuche nach „Rechnung“",
        "SELECT d.id, d.dateiname, left(c.text, 200) AS ausschnitt\n"
        "FROM chunk c\nJOIN textextraktion t ON t.id = c.textextraktion_id\n"
        "JOIN dokument d ON d.id = t.dokument_id\n"
        "WHERE c.tsv @@ websearch_to_tsquery('german', 'Rechnung')\nLIMIT 20",
    ),
    (
        "Dokumente ohne Text",
        "SELECT d.id, d.dateiname, d.typ\nFROM dokument d\n"
        "WHERE NOT EXISTS (SELECT 1 FROM textextraktion t WHERE t.dokument_id = d.id)\nORDER BY d.id",
    ),
    (
        "Zusammenfassungen und Kategorien",
        'SELECT d.dateiname, a.art, a.ergebnis\nFROM "analyse" a\n'
        "JOIN dokument d ON d.id = a.dokument_id\nORDER BY d.dateiname",
    ),
]
