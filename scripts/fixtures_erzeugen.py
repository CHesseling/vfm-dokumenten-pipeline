"""Erzeugt den kleinen Beispielsatz tests/fixtures/mini/ (deterministisch, idempotent).

Aufruf: uv run python scripts/fixtures_erzeugen.py [--audio-neu]
Die Audiodatei wird nur erzeugt, wenn sie fehlt (say/ffmpeg schreiben Zeitstempel
ins Containerformat) - mit --audio-neu erzwungen. Ohne `say` wird sie uebersprungen.
"""

import shutil
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ingest.pdf_render import render_pdf_pages_to_png  # noqa: E402
from tests.fixtures.pdf_bauen import mini_pdf  # noqa: E402

ZIEL = ROOT / "tests" / "fixtures" / "mini"

VERTRAG_ZEILEN = [
    "Liefervertrag",
    "",
    "zwischen der Nordlicht Logistik GmbH, Hamburg, vertreten durch Anna Meier,",
    "und dem Kunden Jonas Becker, Hamburg.",
    "",
    "1. Die Nordlicht Logistik GmbH liefert Lagerdienstleistungen in Hamburg.",
    "2. Der Vertragswert betraegt 12.500,00 EUR (12.500,00 €) netto.",
    "3. Die Zahlung erfolgt auf das Konto DE89 3704 0044 0532 0130 00.",
    "4. Dieser Vertrag wurde am 3. März 2026 in Hamburg geschlossen.",
    "",
    "Hamburg, den 3. März 2026",
    "Anna Meier    Jonas Becker",
]

SPRACHTEXT = (
    "Hallo Anna, hier ist Jonas. Das Treffen zur Lieferung findet am Montag in der "
    "Lagerhalle statt. Ruf mich bitte an unter null vier null, eins zwei drei vier fünf sechs."
)


def _schreibe(pfad: Path, inhalt: bytes) -> None:
    if not pfad.exists() or pfad.read_bytes() != inhalt:
        pfad.write_bytes(inhalt)
        print(f"geschrieben: {pfad.name} ({len(inhalt)} Bytes)")
    else:
        print(f"unveraendert: {pfad.name}")


def scan_bauen(pdf: bytes) -> bytes:
    """Wie tests.fixtures.pdf_bauen.scan_pdf, aber mit festem Datum (reproduzierbare Bytes)."""
    import io

    bilder = [Image.open(io.BytesIO(p)).convert("RGB") for p in render_pdf_pages_to_png(pdf)]
    fest = "D:20260303100000Z"
    puffer = io.BytesIO()
    bilder[0].save(
        puffer, format="PDF", save_all=True, append_images=bilder[1:], creationDate=fest, modDate=fest
    )
    return puffer.getvalue()


def mail_bauen(vertrag: bytes) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Anna Meier <anna.meier@nordlicht-logistik.example>"
    msg["To"] = "Jonas Becker <jonas.becker@example.org>"
    msg["Cc"] = "Redaktion <redaktion@example.org>"
    msg["Subject"] = "Liefervertrag Lagerdienstleistungen"
    msg["Date"] = format_datetime(datetime(2026, 3, 3, 10, 0, 0, tzinfo=timezone.utc))
    msg["Message-ID"] = "<vertrag-2026-03-03@nordlicht-logistik.example>"
    msg.set_content(
        "Hallo Jonas,\n\nanbei der unterschriebene Liefervertrag der Nordlicht Logistik GmbH "
        "(siehe Anhang vertrag.pdf). Bitte pruefe die Konditionen.\n\nViele Gruesse\nAnna Meier\n"
    )
    msg.add_attachment(vertrag, maintype="application", subtype="pdf", filename="vertrag.pdf")
    msg.set_boundary("=====vfm-fixture-grenze=====")
    return msg.as_bytes()


def foto_bauen() -> bytes:
    import io

    bild = Image.new("RGB", (800, 600), (70, 110, 150))
    d = ImageDraw.Draw(bild)
    d.rectangle([100, 200, 700, 400], fill=(245, 245, 245), outline=(20, 20, 20), width=8)
    schrift = ImageFont.load_default(size=90)
    d.text((400, 300), "Lagerhalle 7", font=schrift, fill=(10, 10, 10), anchor="mm")
    exif = Image.Exif()
    exif[0x0132] = "2026:03:03 10:15:00"  # DateTime
    exif.get_ifd(0x8769)[0x9003] = "2026:03:03 10:15:00"  # DateTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (53.0, 33.0, 3.96)  # 53.5511 N
    gps[3], gps[4] = "E", (9.0, 59.0, 37.32)  # 9.9937 E
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=85, exif=exif)
    return puffer.getvalue()


def audio_bauen(ziel: Path, neu: bool) -> None:
    if ziel.exists() and not neu:
        print(f"unveraendert: {ziel.name}")
        return
    if not shutil.which("say") or not shutil.which("ffmpeg"):
        print("say/ffmpeg fehlt - Audio uebersprungen")
        return
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "x.aiff"
        subprocess.run(["say", "-v", "Anna", "-o", str(aiff), SPRACHTEXT], check=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ac", "1", "-ar", "16000",
             "-b:a", "32k", "-map_metadata", "-1", "-fflags", "+bitexact", str(ziel)],
            check=True,
        )
    print(f"geschrieben: {ziel.name} ({ziel.stat().st_size} Bytes)")


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    vertrag = mini_pdf([VERTRAG_ZEILEN])
    _schreibe(ZIEL / "vertrag.pdf", vertrag)
    _schreibe(ZIEL / "scan.pdf", scan_bauen(vertrag))
    _schreibe(ZIEL / "mail.eml", mail_bauen(vertrag))
    _schreibe(ZIEL / "foto.jpg", foto_bauen())
    audio_bauen(ZIEL / "sprachnachricht.m4a", "--audio-neu" in sys.argv)
    gesamt = sum(p.stat().st_size for p in ZIEL.iterdir())
    print(f"Gesamtgroesse: {gesamt} Bytes")
    assert gesamt < 1_000_000


if __name__ == "__main__":
    main()
