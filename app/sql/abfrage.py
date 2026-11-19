"""Read-only-SQL gegen die Pipeline-Datenbank (GUI-Seite /sql und `vfm sql`)."""

import json
import re
import time
from dataclasses import dataclass

import psycopg
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.config import Settings

MAX_ZELLE = 300

_engines: dict[str, Engine] = {}


class SqlFehler(Exception):
    """Fehler einer Benutzer-Abfrage; die Meldung ist die Postgres-Meldung."""


@dataclass
class SqlErgebnis:
    spalten: list[str]
    zeilen: list[tuple]
    abgeschnitten: bool
    dauer_ms: int


def lese_engine(s: Settings) -> Engine:
    """Engine fuer die SQL-Seite: nur die Leserolle (je URL gecacht), nie die Haupt-URL."""
    url = s.sql_readonly_url
    if not url:
        raise SqlFehler(
            "SQL_READONLY_URL ist nicht gesetzt – die SQL-Seite braucht den Lesezugang (siehe .env.example)."
        )
    if url not in _engines:
        _engines[url] = create_engine(url)
    return _engines[url]


def _meldung(fehler: Exception) -> str:
    original = getattr(fehler, "orig", None)
    roh = str(original) if original is not None else str(fehler)
    roh = re.split(r"\n\[SQL:|\n\(Background", roh)[0]
    return roh.strip() or "Unbekannter SQL-Fehler."


def sql_ausfuehren(
    engine: Engine, sql: str, limit: int = 500, timeout_ms: int = 10000
) -> SqlErgebnis:
    if not sql.strip():
        raise SqlFehler("Bitte eine SQL-Abfrage eingeben.")
    start = time.monotonic()
    try:
        with engine.connect() as verbindung:
            try:
                verbindung.exec_driver_sql("SET TRANSACTION READ ONLY")
                verbindung.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
                # Erweitertes Protokoll (prepare=True): Postgres lehnt dann
                # mehrere Anweisungen ab, sodass "COMMIT; DELETE ..." die READ-ONLY-
                # Transaktion nicht verlassen kann. "%" wird zu "%%" maskiert, weil psycopg
                # bei uebergebener Parameterliste Platzhalter parst.
                cursor = verbindung.connection.driver_connection.cursor()
                try:
                    cursor.execute(sql.strip().rstrip(";").replace("%", "%%"), [], prepare=True)
                    if cursor.description is None:
                        raise SqlFehler(
                            "Die Abfrage liefert keine Zeilen (nur SELECT-Abfragen sind sinnvoll)."
                        )
                    spalten = [d.name for d in cursor.description]
                    zeilen = [tuple(z) for z in cursor.fetchmany(limit + 1)]
                finally:
                    cursor.close()
            finally:
                verbindung.rollback()
    except SqlFehler:
        raise
    except psycopg.Error as fehler:
        roh = str(fehler)
        if "multiple commands" in roh:
            raise SqlFehler("Bitte nur eine einzelne SQL-Anweisung ausführen.") from fehler
        raise SqlFehler(roh.strip() or "Unbekannter SQL-Fehler.") from fehler
    except (DBAPIError, SQLAlchemyError) as fehler:
        raise SqlFehler(_meldung(fehler)) from fehler
    abgeschnitten = len(zeilen) > limit
    return SqlErgebnis(
        spalten=spalten,
        zeilen=zeilen[:limit],
        abgeschnitten=abgeschnitten,
        dauer_ms=int((time.monotonic() - start) * 1000),
    )


def zelle_text(wert, maximal: int = MAX_ZELLE) -> str:
    """None -> leer, dict/list -> kompaktes JSON, lange Texte kuerzen."""
    if wert is None:
        return ""
    if isinstance(wert, (dict, list)):
        wert = json.dumps(wert, ensure_ascii=False, separators=(",", ":"), default=str)
    elif isinstance(wert, (bytes, memoryview)):
        wert = f"<{len(bytes(wert))} Bytes>"
    else:
        wert = str(wert)
    if len(wert) > maximal:
        return wert[:maximal] + "…"
    return wert
