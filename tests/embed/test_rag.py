import json

import httpx
import respx

from app.embed.rag import KEINE_ANTWORT, antwort_erzeugen
from app.embed.treffer import SuchTreffer
from app.providers.llm_client import LLMClient


def treffer(nr, text="Inhalt"):
    return SuchTreffer(nr, nr * 10, f"datei{nr}.pdf", text, nr, 0.9, None, None)


def llm():
    return LLMClient(base_url="http://chat/v1", model="m", api_key=None)


def mock():
    return respx.post("http://chat/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Antwort [1]"}}]})
    )


@respx.mock
def test_quellen_nummeriert_im_prompt():
    route = mock()
    r = antwort_erzeugen(llm(), "Frage?", [treffer(1), treffer(2)])
    nachrichten = json.loads(route.calls[0].request.content)["messages"]
    gesamt = json.dumps(nachrichten, ensure_ascii=False)
    assert "[1] datei1.pdf (Dokument 10)" in gesamt and "[2] datei2.pdf (Dokument 20)" in gesamt
    assert "Dazu finde ich in den Dokumenten nichts." in gesamt
    assert r.text == "Antwort [1]" and len(r.quellen) == 2


@respx.mock
def test_keine_treffer_kein_llm_call():
    route = mock()
    r = antwort_erzeugen(llm(), "Frage?", [])
    assert route.call_count == 0
    assert r.text == KEINE_ANTWORT == "Dazu finde ich in den Dokumenten nichts."


@respx.mock
def test_quelle_gekuerzt():
    route = mock()
    antwort_erzeugen(llm(), "F", [treffer(1, "x" * 5000)], max_zeichen_je_quelle=100)
    inhalt = json.dumps(json.loads(route.calls[0].request.content)["messages"])
    assert "x" * 100 in inhalt and "x" * 101 not in inhalt
