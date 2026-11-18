import json

import httpx
import pytest
import respx

from app.analyse.kategorien import Kategorie
from app.providers.decisions import ClefAntwort, DecisionsClient
from app.providers.llm_client import ProviderFehler

URL = "http://cortecs/v1/decisions"
KATS = [Kategorie("Vertrag", "Verträge"), Kategorie("Rechnung", "Rechnungen")]


def _client():
    return DecisionsClient("http://cortecs/v1", "clef-flash:latest", api_key="k")


def _antwort(answer):
    return httpx.Response(200, json={"model": "clef-flash", "answers": [answer],
                                     "usage": {"input_tokens": 10, "output_tokens": 1}})


@respx.mock
def test_choice_anfrage_und_antwort():
    route = respx.post(URL).mock(return_value=_antwort({
        "type": "choice", "name": "kategorie", "choice": "Rechnung", "confidence": 0.82,
        "probabilities": [{"value": "Vertrag", "probability": 0.18}, {"value": "Rechnung", "probability": 0.82}],
    }))
    antwort = _client().klassifiziere("Rechnung Nr. 4", "Welche Kategorie?", KATS)
    assert antwort == ClefAntwort("Rechnung", 0.82, {"Vertrag": 0.18, "Rechnung": 0.82})
    anfrage = route.calls[0].request
    assert anfrage.headers["Authorization"] == "Bearer k"
    assert json.loads(anfrage.content) == {
        "model": "clef-flash:latest",
        "input": "Rechnung Nr. 4",
        "questions": [{"type": "choice", "name": "kategorie", "instructions": "Welche Kategorie?",
                       "choices": [{"value": "Vertrag", "description": "Verträge"},
                                   {"value": "Rechnung", "description": "Rechnungen"}]}],
    }


@respx.mock
def test_verweigerung_ist_fehler():
    respx.post(URL).mock(return_value=_antwort({"type": "refusal", "name": "kategorie"}))
    with pytest.raises(ValueError, match="verweigert"):
        _client().klassifiziere("x", "Frage", KATS)


@respx.mock
def test_schluessel_ungueltig_lesbar():
    respx.post(URL).mock(return_value=httpx.Response(401, json={"error": "nope"}))
    with pytest.raises(ProviderFehler, match="API-Key"):
        _client().klassifiziere("x", "Frage", KATS)
