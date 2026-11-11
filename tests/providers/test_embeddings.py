import httpx
import respx

from app.providers.embeddings import EmbeddingClient


@respx.mock
def test_embed_liefert_vektor():
    respx.post("http://embed.example/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})
    )
    client = EmbeddingClient(base_url="http://embed.example/v1", model="embed-model")

    vektor = client.embed("502 KLs 19/26")

    assert vektor == [0.1, 0.2, 0.3]
    assert client.model == "embed-model"


@respx.mock
def test_embed_viele_batcht_und_ordnet_nach_index():
    import json

    def antwort(request):
        eingabe = json.loads(request.content)["input"]
        daten = [{"index": i, "embedding": [float(t)]} for i, t in enumerate(eingabe)]
        return httpx.Response(200, json={"data": list(reversed(daten))})

    route = respx.post("http://embed.example/v1/embeddings").mock(side_effect=antwort)
    client = EmbeddingClient(base_url="http://embed.example/v1", model="m", batch=2)

    ergebnis = client.embed_viele(["0", "1", "2", "3", "4"])

    assert route.call_count == 3
    assert ergebnis == [[0.0], [1.0], [2.0], [3.0], [4.0]]


@respx.mock
def test_embed_verbindungsfehler_wird_providerfehler():
    from app.providers.llm_client import ProviderFehler

    respx.post("http://embed.example/v1/embeddings").mock(side_effect=httpx.ConnectError("x"))
    client = EmbeddingClient(base_url="http://embed.example/v1", model="m")

    try:
        client.embed("a")
        assert False
    except ProviderFehler as e:
        assert e.rolle == "embed"
        assert "nicht erreichbar" in str(e)
