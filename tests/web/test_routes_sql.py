from app.web.routes_sql import get_sql_engine


def test_sql_seite_zeigt_tabelle(client, engine):
    client.app.dependency_overrides[get_sql_engine] = lambda: engine
    html = client.post("/sql", data={"sql": "SELECT 42 AS antwort, '<b>x</b>' AS t"}).text
    assert "antwort" in html and "42" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_sql_seite_get_zeigt_beispiele(client, engine):
    client.app.dependency_overrides[get_sql_engine] = lambda: engine
    html = client.get("/sql").text
    assert "<textarea" in html and "Dokumente je Typ" in html


def test_sql_seite_zeigt_fehler(client, engine):
    client.app.dependency_overrides[get_sql_engine] = lambda: engine
    html = client.post("/sql", data={"sql": "DELETE FROM lauf"}).text
    assert "read-only" in html


def test_sql_seite_hinweis_abgeschnitten(client, engine):
    client.app.dependency_overrides[get_sql_engine] = lambda: engine
    html = client.post("/sql", data={"sql": "SELECT * FROM generate_series(1,600)"}).text
    assert "500" in html and "abgeschnitten" in html.lower()
