import pytest

from app.config import Settings
from app.sql.abfrage import SqlFehler, SqlErgebnis, lese_engine, sql_ausfuehren
from app.sql.beispiele import BEISPIELE


def test_select_funktioniert(engine):
    e = sql_ausfuehren(engine, "SELECT 1 AS a, 'x' AS b")
    assert isinstance(e, SqlErgebnis)
    assert e.spalten == ["a", "b"]
    assert e.zeilen == [(1, "x")]
    assert not e.abgeschnitten


def test_insert_wird_abgelehnt(engine):
    with pytest.raises(SqlFehler) as fehler:
        sql_ausfuehren(engine, "INSERT INTO lauf (schritt, provider, status) VALUES ('x','y','ok')")
    assert "read-only" in str(fehler.value)


def test_limit_schneidet_ab(engine):
    e = sql_ausfuehren(engine, "SELECT * FROM generate_series(1,10)", limit=3)
    assert len(e.zeilen) == 3
    assert e.abgeschnitten


def test_timeout(engine):
    with pytest.raises(SqlFehler):
        sql_ausfuehren(engine, "SELECT pg_sleep(2)", timeout_ms=100)


def test_leere_abfrage(engine):
    with pytest.raises(SqlFehler, match="Bitte eine SQL-Abfrage eingeben."):
        sql_ausfuehren(engine, "   ")


def test_syntaxfehler_ohne_sqlalchemy_praefix(engine):
    with pytest.raises(SqlFehler) as fehler:
        sql_ausfuehren(engine, "SELEKT 1")
    assert "sqlalchemy" not in str(fehler.value).lower()
    assert "[SQL:" not in str(fehler.value)


def test_verbindung_bleibt_nutzbar_nach_fehler(engine):
    with pytest.raises(SqlFehler):
        sql_ausfuehren(engine, "SELEKT 1")
    assert sql_ausfuehren(engine, "SELECT 1").zeilen == [(1,)]


@pytest.mark.parametrize("titel,sql", BEISPIELE, ids=[b[0] for b in BEISPIELE])
def test_beispiele_laufen_alle(engine, titel, sql):
    sql_ausfuehren(engine, sql)


def test_beispiele_vollstaendig():
    assert len(BEISPIELE) >= 7


@pytest.fixture
def scratch(engine):
    from sqlalchemy import text

    with engine.begin() as c:
        c.execute(text("CREATE TABLE sql_scratch (n int)"))
        c.execute(text("INSERT INTO sql_scratch VALUES (1),(2)"))
    yield
    with engine.begin() as c:
        c.execute(text("DROP TABLE sql_scratch"))


def _anzahl(engine):
    return sql_ausfuehren(engine, "SELECT count(*) FROM sql_scratch").zeilen[0][0]


@pytest.mark.parametrize("praefix", ["COMMIT", "ROLLBACK", "END"])
def test_mehrere_anweisungen_werden_abgelehnt(engine, scratch, praefix):
    with pytest.raises(SqlFehler, match="einzelne SQL-Anweisung"):
        sql_ausfuehren(engine, f"{praefix}; DELETE FROM sql_scratch")
    assert _anzahl(engine) == 2


def test_direktes_delete_aendert_nichts(engine, scratch):
    with pytest.raises(SqlFehler, match="read-only"):
        sql_ausfuehren(engine, "DELETE FROM sql_scratch")
    assert _anzahl(engine) == 2


def test_set_ohne_zeilen_meldung_und_keine_aenderung(engine, scratch):
    with pytest.raises(SqlFehler, match="liefert keine Zeilen"):
        sql_ausfuehren(engine, "SET statement_timeout = 5")
    assert sql_ausfuehren(engine, "SHOW statement_timeout").zeilen[0][0] != "5ms"


def test_abschliessendes_semikolon(engine):
    assert sql_ausfuehren(engine, "SELECT 1;").zeilen == [(1,)]


def test_prozentzeichen_like(engine):
    assert sql_ausfuehren(engine, "SELECT 'abc' LIKE '%b%'").zeilen == [(True,)]


def test_prozentzeichen_modulo(engine):
    assert sql_ausfuehren(engine, "SELECT 5 % 3").zeilen == [(2,)]


def _settings(**kw):
    return Settings(
        _env_file=None, database_url="postgresql+psycopg://x/x", chat_base_url="x", chat_model="x",
        embed_base_url="x", embed_model="x", **kw,
    )


def test_lese_engine_ohne_readonly_url_kein_fallback():
    with pytest.raises(SqlFehler) as fehler:
        lese_engine(_settings())
    assert str(fehler.value) == (
        "SQL_READONLY_URL ist nicht gesetzt – die SQL-Seite braucht den Lesezugang (siehe .env.example)."
    )


def test_lese_engine_mit_readonly_url():
    assert lese_engine(_settings(sql_readonly_url="postgresql+psycopg://l:l@localhost/db")) is not None
