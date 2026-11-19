"""PDF-Text auf drei Wegen: schnell (Textebene), Docling (Layout + OCR), Vision-Modell."""

import functools
import logging
import platform
import threading
from pathlib import Path

from app.ingest.pdf_render import extract_pdf_text, pdf_seitenzahl, render_pdf_pages_to_png
from app.modell_sperre import modell_sperre
from app.providers.llm_client import LLMClient, bild_nachricht

logger = logging.getLogger(__name__)

VISION_TRANSKRIPTION_PROMPT = (
    "Gib den gesamten Text dieser Seite exakt wieder, Zeile für Zeile, ohne Kommentar. "
    "Gibt es keinen Text, antworte mit einer leeren Zeile."
)

# Docling-Converter je artifacts_pfad, lazy gebaut (Modellladen dauert).
_CONVERTER: dict[str, object] = {}
_CONVERTER_LOCK = threading.Lock()


class ExtraktionsFehler(Exception):
    """Text konnte aus der Datei nicht gewonnen werden (kaputte Datei, Modellfehler)."""


def pdf_schnell(inhalt: bytes) -> str:
    return extract_pdf_text(inhalt)


def easyocr_ohne_quantisierung() -> None:
    """Auf ARM: EasyOCR-Reader standardmaessig mit quantize=False.

    EasyOCR quantisiert seine Netze per torch quantize_dynamic. Das dynamisch
    quantisierte Linear stuerzt auf ARM-CPUs mit SME (Apple M4) in Linux-VMs
    (Podman-Machine, Docker Desktop) mit SIGILL ab und reisst den ganzen Prozess
    samt Oberflaeche mit. Docling reicht `quantize` nicht durch, daher hier der
    Standardwert. Ein explizit uebergebenes `quantize` gilt weiter.
    """
    if platform.machine().lower() not in ("aarch64", "arm64"):
        return
    import easyocr

    if getattr(easyocr.Reader, "_vfm_ohne_quantisierung", False):
        return
    original = easyocr.Reader.__init__

    @functools.wraps(original)
    def init(self, *args, **kwargs):
        kwargs.setdefault("quantize", False)
        original(self, *args, **kwargs)

    easyocr.Reader.__init__ = init
    easyocr.Reader._vfm_ohne_quantisierung = True


def _docling_converter(artifacts_pfad: str):
    with _CONVERTER_LOCK:
        if artifacts_pfad not in _CONVERTER:
            easyocr_ohne_quantisierung()
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            ocr = EasyOcrOptions(
                lang=["de"],
                download_enabled=False,
                model_storage_directory=str(Path(artifacts_pfad) / "EasyOcr"),
            )
            optionen = PdfPipelineOptions(artifacts_path=artifacts_pfad, do_ocr=True, ocr_options=ocr)
            optionen.accelerator_options.device = "cpu"
            _CONVERTER[artifacts_pfad] = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=optionen)}
            )
        return _CONVERTER[artifacts_pfad]


def pdf_docling(inhalt: bytes, artifacts_pfad: str) -> str:
    from io import BytesIO

    try:
        from docling.datamodel.base_models import DocumentStream

        with modell_sperre("Docling"):
            converter = _docling_converter(artifacts_pfad)
            ergebnis = converter.convert(DocumentStream(name="dokument.pdf", stream=BytesIO(inhalt)))
        return ergebnis.document.export_to_markdown()
    except Exception as fehler:
        raise ExtraktionsFehler(f"Docling konnte das PDF nicht lesen: {fehler}") from fehler


def pdf_vision(inhalt: bytes, client: LLMClient, max_seiten: int = 20) -> str:
    try:
        gesamt = pdf_seitenzahl(inhalt)
        seiten = render_pdf_pages_to_png(inhalt, max_seiten=max_seiten)
    except Exception as fehler:
        raise ExtraktionsFehler(f"PDF konnte nicht gerendert werden: {fehler}") from fehler
    if not seiten:
        raise ExtraktionsFehler("PDF enthält keine lesbaren Seiten")

    texte = []
    for nummer, png in enumerate(seiten, start=1):
        text = client.chat_text([bild_nachricht(VISION_TRANSKRIPTION_PROMPT, [(png, "image/png")])])
        texte.append(f"\n\n--- Seite {nummer} ---\n\n{text}" if nummer > 1 else text)
    ergebnis = "".join(texte)
    if gesamt > max_seiten:
        ergebnis += f"\n\n[Hinweis: nur die ersten {max_seiten} von {gesamt} Seiten gelesen]"
    return ergebnis
