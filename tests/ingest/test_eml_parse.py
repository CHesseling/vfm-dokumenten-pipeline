from pathlib import Path

from app.ingest.eml_parse import extract_eml_attachments, parse_eml_message

MINI = Path(__file__).parent.parent / "fixtures" / "mini"
FIXTURE_EML = MINI / "mail.eml"
FIXTURE_PDF = MINI / "vertrag.pdf"


def test_parse_eml_message_extrahiert_absender_betreff_und_body():
    eml_bytes = FIXTURE_EML.read_bytes()

    message = parse_eml_message(eml_bytes, message_id="upload:test123")

    assert message["id"] == "upload:test123"
    assert message["from"]["emailAddress"]["address"] == "anna.meier@nordlicht-logistik.example"
    assert "Liefervertrag" in message["subject"]
    assert "Nordlicht Logistik GmbH" in message["body"]["content"]
    assert message["hasAttachments"] is True
    assert message["receivedDateTime"] == "2026-03-03T10:00:00Z"


def test_extract_eml_attachments_findet_pdf():
    eml_bytes = FIXTURE_EML.read_bytes()

    anhaenge = extract_eml_attachments(eml_bytes)

    assert len(anhaenge) == 1
    assert anhaenge[0]["name"] == "vertrag.pdf"
    assert anhaenge[0]["@odata.type"] == "#microsoft.graph.fileAttachment"

    import base64

    dekodiert = base64.b64decode(anhaenge[0]["contentBytes"])
    assert dekodiert == FIXTURE_PDF.read_bytes()


def test_parse_eml_message_ohne_anhang():
    eml_bytes = (
        b"From: Pressestelle <presse@gericht.de>\r\n"
        b"To: redaktion@ndr.de\r\n"
        b"Subject: Terminaenderung im Verfahren 522 Ks 3/24\r\n"
        b"Date: Mon, 01 Sep 2026 10:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Der Termin am 09.09.2026 wurde aufgehoben.\r\n"
    )

    message = parse_eml_message(eml_bytes, message_id="upload:abc")
    anhaenge = extract_eml_attachments(eml_bytes)

    assert message["from"]["emailAddress"]["address"] == "presse@gericht.de"
    assert "aufgehoben" in message["body"]["content"]
    assert message["hasAttachments"] is False
    assert anhaenge == []


def _mail_mit_html_tabelle(plain: str, html_inhalt: str) -> bytes:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "Pressestelle.Strafgerichte@kg.berlin.de"
    msg["Subject"] = "Terminsaufhebungen für den Wochenplan am 28.03.2025"
    msg["Date"] = "Thu, 27 Mar 2025 14:17:39 +0100"
    msg.set_content(plain)
    msg.add_alternative(html_inhalt, subtype="html")
    return msg.as_bytes()


def test_parse_eml_message_bevorzugt_html_tabelle_mit_zeilenstruktur():
    # Im Klartext-Teil zerfaellt die Tabelle zu einer Zelle pro Zeile - dann ist
    # nicht mehr erkennbar, welche Zahl Kammer, Nummer oder Saal ist.
    plain = "Kammer\nBeginn\nSaal\n23\n11/24\n09.30\nA\n739\n1/25\n13.30\n35\nKs 10/24\n09.30\nA\n537"
    html_inhalt = """<html><head><style>p {margin:0}</style></head><body>
    <p>Tagesplan vom</p><p><b>Freitag, 28.&nbsp;März 2025</b></p>
    <table>
      <tr><td>Kammer</td><td></td><td>Beginn</td><td colspan="2">Saal</td></tr>
      <tr><td><p>23</p></td><td>11/24</td><td>09.30</td><td>A</td><td>739</td></tr>
      <tr><td></td><td>1/25</td><td>13.30</td><td></td><td></td></tr>
      <tr><td>35</td><td>Ks 10/24</td><td>09.30</td><td>A</td><td>537</td></tr>
    </table>
    <p>Mit freundlichen Gr&uuml;&szlig;en</p></body></html>"""

    body = parse_eml_message(_mail_mit_html_tabelle(plain, html_inhalt), "x")["body"]["content"]

    assert "Freitag, 28. März 2025" in body
    assert "23 | 11/24 | 09.30 | A | 739" in body
    assert "\n| 1/25 | 13.30\n" in body  # leere Kammer-Zelle bleibt erkennbar
    assert "35 | Ks 10/24 | 09.30 | A | 537" in body
    assert "Mit freundlichen Grüßen" in body
    assert "margin" not in body


def test_parse_eml_message_nutzt_ohne_html_tabelle_weiter_den_klartext():
    body = parse_eml_message(
        _mail_mit_html_tabelle("Klartext-Version", "<html><body><p>HTML-Version</p></body></html>"), "x"
    )["body"]["content"]

    assert body.strip() == "Klartext-Version"
