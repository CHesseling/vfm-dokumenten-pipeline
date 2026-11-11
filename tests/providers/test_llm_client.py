from datetime import date, time

import httpx
import respx
from pydantic import BaseModel

from app.providers.llm_client import (
    LLMClient,
    LLMExtractionError,
    LLMGesamtTimeoutError,
    ProviderFehler,
    bild_nachricht,
)


class Beispielschema(BaseModel):
    wert: str


@respx.mock
def test_chat_json_erfolg():
    respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"wert": "ok"}'}}]},
        )
    )
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    ergebnis = client.chat_json([{"role": "user", "content": "hallo"}], Beispielschema)

    assert ergebnis.wert == "ok"


@respx.mock
def test_chat_json_korrigiert_nach_ungueltigem_json():
    route = respx.post("http://llm.example/v1/chat/completions")
    route.side_effect = [
        httpx.Response(200, json={"choices": [{"message": {"content": "kein json"}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"wert": "korrigiert"}'}}]}),
    ]
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    ergebnis = client.chat_json([{"role": "user", "content": "hallo"}], Beispielschema)

    assert ergebnis.wert == "korrigiert"
    assert route.call_count == 2


@respx.mock
def test_chat_json_wirft_nach_zweitem_fehlschlag():
    respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "immer noch kaputt"}}]})
    )
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    try:
        client.chat_json([{"role": "user", "content": "hallo"}], Beispielschema)
        assert False, "sollte LLMExtractionError werfen"
    except LLMExtractionError:
        pass


@respx.mock
def test_chat_json_with_image_baut_multimodalen_content():
    route = respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"wert": "bild-ok"}'}}]})
    )
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    ergebnis = client.chat_json_with_image(
        "system", "user-text", [(b"\x89PNG...", "image/png")], Beispielschema
    )

    assert ergebnis.wert == "bild-ok"
    gesendeter_body = route.calls[0].request.content
    assert b"image_url" in gesendeter_body
    assert b"data:image/png;base64" in gesendeter_body


def test_model_attribut_ist_oeffentlich():
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")
    assert client.model == "qwen3"


@respx.mock
def test_chat_json_korrigiert_nach_leerem_content():
    """Reasoning-lastige Modelle (z. B. DeepSeek) koennen bei knappem Token-Budget
    content=null zurueckgeben, statt eines Strings. Das darf nicht als roher
    TypeError durchschlagen, sondern muss denselben Korrektur-Versuch ausloesen
    wie ungueltiges JSON."""
    route = respx.post("http://llm.example/v1/chat/completions")
    route.side_effect = [
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"wert": "diesmal-ok"}'}}]}),
    ]
    client = LLMClient(base_url="http://llm.example/v1", model="deepseek/deepseek-v4.1-flash")

    ergebnis = client.chat_json([{"role": "user", "content": "hallo"}], Beispielschema)

    assert ergebnis.wert == "diesmal-ok"
    assert route.call_count == 2


@respx.mock
def test_chat_json_wirft_nach_zweitem_leerem_content():
    respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
    )
    client = LLMClient(base_url="http://llm.example/v1", model="deepseek/deepseek-v4.1-flash")

    try:
        client.chat_json([{"role": "user", "content": "hallo"}], Beispielschema)
        assert False, "sollte LLMExtractionError werfen"
    except LLMExtractionError as fehler:
        assert "content" in str(fehler).lower() or "inhalt" in str(fehler).lower()


def test_chat_completion_erzwingt_gesamt_timeout_ohne_wiederholung():
    """httpx' eigener Timeout misst nur Luecken zwischen Bytes, nicht die
    Gesamtdauer einer Anfrage - manche LLM-Gateways halten die Verbindung
    waehrend langer Generierungen per Keep-Alive-Bytes am Leben, wodurch
    httpx' Timeout nie ausloest. Simuliert hier durch eine Anfrage, die
    laenger braucht als das konfigurierte Gesamt-Zeitbudget - muss trotzdem
    zuverlaessig abgebrochen werden. Und zwar OHNE Wiederholung: bei
    temperature=0 braucht dieselbe Anfrage beim naechsten Versuch genauso
    lange (auf dem Server kosteten drei identische Versuche 9 Minuten pro
    Wochenplan-Tag)."""
    import time

    client = LLMClient(base_url="http://llm.example/v1", model="qwen3", gesamt_timeout=0.2)
    aufrufe = []

    def _langsame_anfrage(messages, response_format=None):
        aufrufe.append(1)
        time.sleep(1)
        return '{"wert": "zu spaet"}'

    client._chat_completion_request = _langsame_anfrage

    try:
        client._chat_completion([{"role": "user", "content": "hallo"}])
        assert False, "sollte LLMGesamtTimeoutError werfen"
    except LLMGesamtTimeoutError:
        pass
    assert len(aufrufe) == 1


def test_chat_completion_wiederholt_netzwerkfehler():
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")
    aufrufe = []

    def _wackelige_anfrage(messages, response_format=None):
        aufrufe.append(1)
        if len(aufrufe) < 3:
            raise httpx.ConnectError("Verbindung abgelehnt")
        return '{"wert": "ok"}'

    client._chat_completion_request = _wackelige_anfrage

    assert client._chat_completion([{"role": "user", "content": "hallo"}]) == '{"wert": "ok"}'
    assert len(aufrufe) == 3


def test_chat_completion_wiederholt_read_timeout_nicht():
    # Auch httpx' eigenes ReadTimeout (lange Generierung) ist deterministisch.
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")
    aufrufe = []

    def _zu_langsam(messages, response_format=None):
        aufrufe.append(1)
        raise httpx.ReadTimeout("zu langsam")

    client._chat_completion_request = _zu_langsam

    try:
        client._chat_completion([{"role": "user", "content": "hallo"}])
        assert False, "sollte ReadTimeout werfen"
    except httpx.ReadTimeout:
        pass
    assert len(aufrufe) == 1


def test_httpx_timeout_liegt_hinter_dem_gesamt_budget():
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3", gesamt_timeout=600)

    assert client._client.timeout.read > 600


def test_doppelte_schluessel_gelten_als_ungueltig():
    # Im A/B-Test schrieb gemma4 '{"verfahren": [A], "verfahren": [B], ...}' -
    # json.loads behaelt still nur den LETZTEN Wert, 14 von 15 Verfahren gingen
    # verloren und die Antwort galt trotzdem als gueltig.
    ergebnis, fehler = LLMClient._parsen_und_validieren(
        '{"wert": "erster", "wert": "zweiter"}', Beispielschema
    )

    assert ergebnis is None
    assert "doppelt" in str(fehler).lower()


class _MitUhrzeit(BaseModel):
    beginn: time
    tag: date


def _gesendetes_format(route) -> dict:
    import json

    return json.loads(route.calls.last.request.content)["response_format"]


@respx.mock
def test_chat_json_nutzt_standardmaessig_json_modus():
    route = respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"wert": "ok"}'}}]})
    )
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    client.chat_json([{"role": "user", "content": "hallo"}], Beispielschema)

    assert _gesendetes_format(route) == {"type": "json_object"}


@respx.mock
def test_chat_json_mit_structured_outputs_schickt_schema_mit_hhmm_muster():
    # Pydantic beschreibt `time` als format "time" (RFC 3339, mit Zeitzone) -
    # eine Grammatik zwingt das Modell dann zu erfundenen Offsets wie
    # "09:30:00-09:30" (im A/B-Test beobachtet). Fuer das LLM daher HH:MM.
    route = respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": '{"beginn": "09:30", "tag": "2026-06-08"}'}}]}
        )
    )
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3", structured_outputs=True)

    ergebnis = client.chat_json([{"role": "user", "content": "hallo"}], _MitUhrzeit)

    assert ergebnis.beginn == time(9, 30)
    gesendet = _gesendetes_format(route)
    assert gesendet["type"] == "json_schema"
    assert gesendet["json_schema"]["name"] == "_MitUhrzeit"
    eigenschaften = gesendet["json_schema"]["schema"]["properties"]
    assert "format" not in eigenschaften["beginn"]
    assert eigenschaften["beginn"]["pattern"] == "^([01][0-9]|2[0-3]):[0-5][0-9]$"
    assert eigenschaften["tag"]["format"] == "date"


@respx.mock
def test_structured_outputs_faellt_bei_400_auf_json_modus_zurueck():
    # Unterstuetzt der Server ein Schema-Detail nicht, scheitert sonst JEDE
    # Anfrage - ein ganzer Backfill waere verloren.
    route = respx.post("http://llm.example/v1/chat/completions")
    route.side_effect = [
        httpx.Response(400, json={"error": "unsupported format 'date'"}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"wert": "ok"}'}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": '{"wert": "weiter"}'}}]}),
    ]
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3", structured_outputs=True)

    assert client.chat_json([{"role": "user", "content": "hallo"}], Beispielschema).wert == "ok"
    assert client.chat_json([{"role": "user", "content": "nochmal"}], Beispielschema).wert == "weiter"

    import json

    formate = [json.loads(aufruf.request.content)["response_format"]["type"] for aufruf in route.calls]
    assert formate == ["json_schema", "json_object", "json_object"]  # danach dauerhaft JSON-Modus


URL = "http://llm.example/v1/chat/completions"


def _antwort(inhalt):
    return httpx.Response(200, json={"choices": [{"message": {"content": inhalt}}]})


@respx.mock
def test_chat_text_ohne_response_format():
    import json

    route = respx.post(URL).mock(return_value=_antwort("  Hallo \n"))
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    assert client.chat_text([{"role": "user", "content": "hi"}]) == "Hallo"
    assert "response_format" not in json.loads(route.calls[0].request.content)


@respx.mock
def test_chat_text_entfernt_think_block():
    respx.post(URL).mock(return_value=_antwort("<think>xx</think>Antwort"))
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    assert client.chat_text([{"role": "user", "content": "hi"}]) == "Antwort"


@respx.mock
def test_extra_body_wird_mitgeschickt():
    import json

    route = respx.post(URL).mock(return_value=_antwort('{"wert": "ok"}'))
    client = LLMClient(
        base_url="http://llm.example/v1", model="qwen3", extra_body={"reasoning_effort": "none"}
    )

    client.chat_json([{"role": "user", "content": "hi"}], Beispielschema)

    assert json.loads(route.calls[0].request.content)["reasoning_effort"] == "none"


def test_bild_mit_mime():
    nachricht = bild_nachricht("t", [(b"x", "image/jpeg")])
    assert nachricht["role"] == "user"
    assert nachricht["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@respx.mock
def test_verbindungsfehler_wird_providerfehler():
    respx.post(URL).mock(side_effect=httpx.ConnectError("nope"))
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    try:
        client.chat_text([{"role": "user", "content": "hi"}])
        assert False, "sollte ProviderFehler werfen"
    except ProviderFehler as e:
        assert "nicht erreichbar" in str(e)
        assert e.rolle == "chat"
        assert str(e) == "chat: nicht erreichbar (qwen3 @ http://llm.example/v1)"


@respx.mock
def test_404_wird_modell_nicht_gefunden():
    respx.post(URL).mock(return_value=httpx.Response(404, json={"error": "x"}))
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3", rolle="vision")

    try:
        client.chat_json([{"role": "user", "content": "hi"}], Beispielschema)
        assert False, "sollte ProviderFehler werfen"
    except ProviderFehler as e:
        assert e.meldung == "Modell nicht gefunden"
        assert e.rolle == "vision"


@respx.mock
def test_401_wird_key_fehler():
    respx.post(URL).mock(return_value=httpx.Response(401, json={"error": "x"}))
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")

    try:
        client.chat_text([{"role": "user", "content": "hi"}])
        assert False, "sollte ProviderFehler werfen"
    except ProviderFehler as e:
        assert e.meldung == "API-Key fehlt oder ist ungültig"


@respx.mock
def test_serverfehler_5xx_mit_antworttext(monkeypatch):
    import pytest

    monkeypatch.setattr("tenacity.nap.time.sleep", lambda s: None)
    respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="model requires more system memory (8 GiB)")
    )
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3")
    with pytest.raises(ProviderFehler) as e:
        client.chat_text([{"role": "user", "content": "x"}])
    assert "Serverfehler 500: model requires more system memory" in e.value.meldung


@respx.mock
def test_zeitueberschreitung_wird_providerfehler():
    import pytest

    respx.post("http://llm.example/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("x"))
    client = LLMClient(base_url="http://llm.example/v1", model="qwen3", gesamt_timeout=42)
    with pytest.raises(ProviderFehler) as e:
        client.chat_text([{"role": "user", "content": "x"}])
    assert e.value.meldung == "Zeitüberschreitung nach 42 s"


def test_gesamt_timeout_wird_providerfehler():
    from app.providers.llm_client import provider_fehler_abbilden

    f = provider_fehler_abbilden(LLMGesamtTimeoutError("x"), "chat", "http://x/v1", "m", timeout=600)
    assert f is not None and f.meldung == "Zeitüberschreitung nach 600 s"
