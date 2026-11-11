import httpx
import pytest
import respx

from app.providers.rerank import ApiReranker, KeinReranker, LokalerReranker


@respx.mock
def test_rerank_sortiert_nach_relevanz():
    respx.post("http://rerank.example/v1/rerank").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.2},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 2, "relevance_score": 0.5},
                ]
            },
        )
    )
    client = ApiReranker(base_url="http://rerank.example/v1", model="rerank-model", api_key=None, timeout=5.0)

    reihenfolge = client.rerank("Betaeubungsmittel Charlottenburg", ["doc0", "doc1", "doc2"])

    assert reihenfolge == [(1, 0.9), (2, 0.5), (0, 0.2)]


def test_kein_reranker_behaelt_reihenfolge():
    assert KeinReranker().rerank("frage", ["a", "b"]) == [(0, 0.0), (1, 0.0)]


@pytest.fixture(autouse=True)
def leerer_cache(monkeypatch):
    monkeypatch.setattr("app.providers.rerank._ENCODER", {})


def test_lokaler_reranker_sortiert(monkeypatch):
    aufrufe = []

    class FakeCrossEncoder:
        def predict(self, paare):
            assert paare == [("frage", "a"), ("frage", "b")]
            return [0.1, 0.9]

    def lader(modell):
        aufrufe.append(modell)
        return FakeCrossEncoder()

    monkeypatch.setattr("app.providers.rerank._lade_cross_encoder", lader)
    reranker = LokalerReranker("mein-modell")
    assert aufrufe == []

    assert reranker.rerank("frage", ["a", "b"]) == [(1, 0.9), (0, 0.1)]
    reranker.rerank("frage", ["a", "b"])
    assert aufrufe == ["mein-modell"]


@pytest.mark.modelle
def test_lokaler_reranker_echt():
    from app.config import Settings

    reranker = LokalerReranker(Settings.model_fields["rerank_model"].default)
    ergebnis = reranker.rerank(
        "Wann ist die Verhandlung gegen den Angeklagten?",
        ["Das Wetter in Berlin ist heute sonnig.", "Die Verhandlung gegen den Angeklagten beginnt am Montag um 9 Uhr."],
    )
    assert ergebnis[0][0] == 1


@respx.mock
def test_api_reranker_404_ohne_retry():
    from app.providers.llm_client import ProviderFehler

    route = respx.post("http://rerank.example/v1/rerank").mock(return_value=httpx.Response(404))
    client = ApiReranker(base_url="http://rerank.example/v1", model="m")
    with pytest.raises(ProviderFehler) as e:
        client.rerank("f", ["a"])
    assert route.call_count == 1
    assert e.value.rolle == "rerank" and e.value.meldung == "Modell nicht gefunden"


@respx.mock
def test_api_reranker_500_providerfehler(monkeypatch):
    from app.providers.llm_client import ProviderFehler

    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    respx.post("http://rerank.example/v1/rerank").mock(return_value=httpx.Response(500, text="kaputt"))
    client = ApiReranker(base_url="http://rerank.example/v1", model="m")
    with pytest.raises(ProviderFehler) as e:
        client.rerank("f", ["a"])
    assert "Serverfehler 500: kaputt" in e.value.meldung


def test_modell_cache_ueber_instanzen_und_threads(monkeypatch):
    import threading
    import time

    aufrufe = []

    class Fake:
        def predict(self, paare):
            return [0.5 for _ in paare]

    def lader(modell):
        aufrufe.append(modell)
        time.sleep(0.1)
        return Fake()

    monkeypatch.setattr("app.providers.rerank._lade_cross_encoder", lader)
    threads = [
        threading.Thread(target=lambda: LokalerReranker("m").rerank("f", ["a"])) for _ in range(4)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    LokalerReranker("m").rerank("f", ["a"])
    assert aufrufe == ["m"]
