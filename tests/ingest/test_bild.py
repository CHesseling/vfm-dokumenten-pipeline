import base64
import io

import httpx
import respx
from PIL import Image

from app.ingest.bild import bild_als_jpeg, bild_metadaten, bild_ocr
from app.providers.llm_client import LLMClient


def _jpeg_mit_gps() -> bytes:
    bild = Image.new("RGB", (120, 80), "white")
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "EOS 5"
    exif.get_ifd(0x8769)[0x9003] = "2026:03:12 14:30:05"
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (53.0, 33.0, 0.0)
    gps[3] = "E"
    gps[4] = (9.0, 59.0, 24.0)
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", exif=exif)
    return puffer.getvalue()


def test_bild_metadaten_gps():
    meta = bild_metadaten(_jpeg_mit_gps())

    assert meta["breite"] == 120 and meta["hoehe"] == 80
    assert meta["aufnahmedatum"] == "2026-03-12T14:30:05"
    assert meta["kamera_marke"] == "Canon" and meta["kamera_modell"] == "EOS 5"
    assert abs(meta["gps"]["lat"] - 53.55) < 0.001
    assert abs(meta["gps"]["lon"] - 9.99) < 0.001


def test_bild_metadaten_ohne_exif():
    puffer = io.BytesIO()
    Image.new("RGB", (10, 5)).save(puffer, format="PNG")

    meta = bild_metadaten(puffer.getvalue())

    assert meta == {"breite": 10, "hoehe": 5}


def test_bild_als_jpeg_verkleinert():
    puffer = io.BytesIO()
    Image.new("RGBA", (4000, 100), "red").save(puffer, format="PNG")

    jpeg = bild_als_jpeg(puffer.getvalue())

    assert jpeg.startswith(b"\xff\xd8")
    assert max(Image.open(io.BytesIO(jpeg)).size) == 2048


@respx.mock
def test_bild_ocr_schickt_jpeg():
    route = respx.post("http://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Text im Bild"}}]})
    )
    client = LLMClient(base_url="http://llm.example/v1", model="vl")
    puffer = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(puffer, format="PNG")

    assert bild_ocr(puffer.getvalue(), client) == "Text im Bild"
    assert "data:image/jpeg;base64" in route.calls[0].request.content.decode()
