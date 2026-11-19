from app.web.routes_api_hilfe import endpunkte


def test_api_hilfe_listet_alle_endpunkte(client):
    html = client.get("/api-hilfe").text
    for pfad in ("/api/suche", "/api/dokumente/{dokument_id}", "/api/entitaeten", "/api/frage"):
        assert f"<code>{pfad}</code>" in html
    assert "Dokumente durchsuchen" in html  # summary aus der Route
    assert "top_k" in html and "Maximale Anzahl Treffer" in html  # Parameter mit Beschreibung
    assert "dokument_id" in html and "ausschnitt" in html  # Antwortfelder
    assert "/openapi.json" in html and "/docs" in html


def test_api_hilfe_beispiele(client):
    html = client.get("/api-hilfe").text
    assert "curl &#39;http://testserver/api/suche?q=Rechnung&amp;modus=volltext&amp;top_k=3&#39;" in html
    assert "http://testserver/api/dokumente/1" in html
    assert "-X POST" in html and "Wie hoch ist der Vertragswert?" in html


def test_api_hilfe_ohne_token(client):
    html = client.get("/api-hilfe").text
    assert "Kein <code>API_TOKEN</code> gesetzt" in html
    assert "Authorization: Bearer DEIN_TOKEN" not in html


def test_api_hilfe_mit_token_zeigt_wert_nicht(client, einstellungen):
    einstellungen.api_token = "streng-geheim-123"
    html = client.get("/api-hilfe").text
    assert "Ein <code>API_TOKEN</code> ist gesetzt" in html
    assert "Authorization: Bearer DEIN_TOKEN" in html
    assert "streng-geheim-123" not in html


def test_endpunkte_ignoriert_nicht_api_pfade():
    openapi = {"paths": {"/status": {"get": {"summary": "x"}}, "/api/x": {"get": {"summary": "y"}}}}
    assert [e["pfad"] for e in endpunkte(openapi, "http://h", False)] == ["/api/x"]


def test_navigation_hat_api_link(client):
    assert 'href="/api-hilfe"' in client.get("/status").text
