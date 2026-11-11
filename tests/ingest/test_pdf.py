import json
import os
from pathlib import Path

import httpx
import pytest
import respx

from app.ingest import pdf as pdf_modul
from app.ingest.pdf import ExtraktionsFehler, pdf_docling, pdf_schnell, pdf_vision
from app.providers.llm_client import LLMClient
from tests.fixtures.pdf_bauen import mini_pdf, scan_pdf


def test_pdf_schnell_text():
    assert "Hallo Welt" in pdf_schnell(mini_pdf([["Hallo Welt"]]))


def test_scan_pdf_hat_keinen_text():
    assert pdf_schnell(scan_pdf(mini_pdf([["Hallo Welt"]]))).strip() == ""


@respx.mock
def test_pdf_vision_pro_seite():
    route = respx.post("http://llm.example/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json={"choices": [{"message": {"content": "Seite eins"}}]}),
            httpx.Response(200, json={"choices": [{"message": {"content": "Seite zwei"}}]}),
        ]
    )
    client = LLMClient(base_url="http://llm.example/v1", model="vl")

    text = pdf_vision(mini_pdf([["A"], ["B"]]), client)

    assert route.call_count == 2
    assert "--- Seite 2 ---" in text
    assert "Seite eins" in text and "Seite zwei" in text
    assert "data:image/png" in route.calls[0].request.content.decode()


@respx.mock
def test_pdf_vision_begrenzt_seiten():
    route = respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})
    )
    client = LLMClient(base_url="http://llm.example/v1", model="vl")

    text = pdf_vision(mini_pdf([["A"], ["B"], ["C"]]), client, max_seiten=2)

    assert route.call_count == 2
    assert "nur die ersten 2 von 3 Seiten" in text


def test_pdf_vision_ungueltig_wirft_extraktionsfehler():
    client = LLMClient(base_url="http://llm.example/v1", model="vl")
    with pytest.raises(ExtraktionsFehler):
        pdf_vision(b"kein pdf", client)


def test_pdf_docling_kaputt_wirft_extraktionsfehler(monkeypatch):
    class KaputterConverter:
        def convert(self, *args, **kwargs):
            raise RuntimeError("kaputt")

    monkeypatch.setattr(pdf_modul, "_docling_converter", lambda pfad: KaputterConverter())
    with pytest.raises(ExtraktionsFehler, match="kaputt"):
        pdf_docling(mini_pdf([["x"]]), "/egal")


ARTIFACTS = os.environ.get("VFM_DOCLING_ARTIFACTS", "/models/docling")


@pytest.mark.modelle
def test_pdf_docling_scan():
    if not Path(ARTIFACTS).is_dir():
        pytest.skip(f"Docling-Modelle fehlen: {ARTIFACTS}")
    scan = scan_pdf(mini_pdf([["Kaufvertrag Rechnung 250000 Euro"]]))

    text = pdf_docling(scan, ARTIFACTS)

    assert "Kaufvertrag" in text


@respx.mock
def test_pdf_vision_rendert_nur_max_seiten(monkeypatch):
    import app.ingest.pdf as pdf_modul

    gerendert = []
    echt = pdf_modul.render_pdf_pages_to_png

    def spion(*a, **k):
        seiten = echt(*a, **k)
        gerendert.append(len(seiten))
        return seiten

    monkeypatch.setattr(pdf_modul, "render_pdf_pages_to_png", spion)
    respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})
    )
    client = LLMClient(base_url="http://llm.example/v1", model="vl")
    text = pdf_vision(mini_pdf([["A"], ["B"], ["C"]]), client, max_seiten=1)
    assert gerendert == [1]
    assert "nur die ersten 1 von 3 Seiten" in text
