def test_terminal_leitet_auf_ttyd_weiter(client):
    antwort = client.get("/terminal")
    assert antwort.status_code == 302
    assert antwort.headers["location"] == "http://testserver:7681/"


def test_terminal_port_aus_einstellungen(client, einstellungen):
    einstellungen.terminal_port = 9100
    antwort = client.get("/terminal", headers={"host": "server.example:8999"})
    assert antwort.headers["location"] == "http://server.example:9100/"


def test_terminal_abgeschaltet(client, einstellungen):
    einstellungen.terminal = "aus"
    antwort = client.get("/terminal")
    assert antwort.status_code == 200
    assert "abgeschaltet" in antwort.text


def test_navigation_hat_terminal_link(client):
    assert 'href="/terminal"' in client.get("/status").text
