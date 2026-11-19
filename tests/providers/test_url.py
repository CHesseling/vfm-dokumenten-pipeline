from app.providers.llm_client import ProviderFehler
from app.providers.url import ohne_zugangsdaten


def test_ohne_zugangsdaten():
    assert ohne_zugangsdaten("https://u:geheim@host:8443/v1") == "https://host:8443/v1"
    assert ohne_zugangsdaten("http://host/v1") == "http://host/v1"
    assert ohne_zugangsdaten(None) is None


def test_ungueltiger_port_wirft_nicht():
    r = ohne_zugangsdaten("https://u:p@host:abc/v1")
    assert "p@" not in r and r.endswith("host:abc/v1")


def test_provider_fehler_ohne_zugangsdaten():
    e = ProviderFehler("chat", "https://user:geheim@host/v1", "m", "nicht erreichbar")
    assert "geheim" not in str(e) and "geheim" not in e.base_url
