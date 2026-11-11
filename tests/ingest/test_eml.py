from email.message import EmailMessage

from app.ingest.eml import eml_lesen
from tests.fixtures.pdf_bauen import mini_pdf


def _mail() -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "Anna <anna@x.de>"
    msg["To"] = "a@x.de"
    msg["Cc"] = "b@x.de"
    msg["Subject"] = "Rechnung März"
    msg["Date"] = "Tue, 08 Sep 2026 13:22:46 +0000"
    return msg


def test_eml_text_und_metadaten():
    msg = _mail()
    msg.set_content("Guten Tag, anbei die Unterlagen.")

    eml = eml_lesen(msg.as_bytes())

    assert eml.metadaten["absender"] == "anna@x.de"
    assert eml.metadaten["empfaenger"] == ["a@x.de", "b@x.de"]
    assert eml.metadaten["betreff"] == "Rechnung März"
    assert eml.metadaten["datum"] == "2026-09-08T13:22:46Z"
    assert eml.text.startswith("Von: ")
    assert "Betreff: Rechnung März" in eml.text
    assert eml.text.endswith("Guten Tag, anbei die Unterlagen.")
    assert eml.anhaenge == []


def test_eml_anhaenge():
    msg = _mail()
    msg.set_content("Siehe Anhang.")
    pdf = mini_pdf([["Rechnung"]])
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="rechnung.pdf")

    eml = eml_lesen(msg.as_bytes())

    assert eml.anhaenge[0][0] == "rechnung.pdf"
    assert eml.anhaenge[0][1] == pdf


def test_html_tabelle_bleibt_zeilenweise():
    msg = _mail()
    msg.set_content("Kammer\n6\n09:00\nSaal 1")
    msg.add_alternative(
        "<html><body><table><tr><td>Kammer</td><td>Beginn</td><td>Saal</td></tr>"
        "<tr><td>6</td><td>09:00</td><td>Saal 1</td></tr></table></body></html>",
        subtype="html",
    )

    eml = eml_lesen(msg.as_bytes())

    assert "Kammer | Beginn | Saal" in eml.text
    assert "6 | 09:00 | Saal 1" in eml.text


def test_weitergeleitete_mail_als_anhang():
    innen = EmailMessage()
    innen["From"] = "x@y.de"
    innen["To"] = "z@y.de"
    innen["Subject"] = "Innerer Betreff"
    innen.set_content("Innen")
    msg = _mail()
    msg.set_content("Weitergeleitet")
    msg.add_attachment(innen)

    eml = eml_lesen(msg.as_bytes())

    assert len(eml.anhaenge) == 1
    name, daten = eml.anhaenge[0]
    assert name.endswith(".eml")
    assert eml_lesen(daten).metadaten["betreff"] == "Innerer Betreff"


def test_namenlose_anhaenge_bekommen_namen_mit_endung():
    msg = _mail()
    msg.set_content("x")
    pdf = mini_pdf([["A"]])
    msg.add_attachment(pdf, maintype="application", subtype="pdf")
    msg.add_attachment(pdf, maintype="application", subtype="pdf")

    eml = eml_lesen(msg.as_bytes())

    assert [n for n, _ in eml.anhaenge] == ["anhang-1.pdf", "anhang-2.pdf"]


def test_inline_pdf_mit_dateiname_ist_anhang_signaturbild_nicht():
    msg = _mail()
    msg.set_content("x")
    msg.add_attachment(mini_pdf([["A"]]), maintype="application", subtype="pdf",
                       filename="inline.pdf", disposition="inline")
    msg.add_attachment(b"\x89PNG\r\n\x1a\nxx", maintype="image", subtype="png",
                       filename="logo.png", disposition="inline", cid="<logo@x>")

    eml = eml_lesen(msg.as_bytes())

    assert [n for n, _ in eml.anhaenge] == ["inline.pdf"]


def _roh(kopf_teil: str) -> bytes:
    return ("From: a@x.de\r\nTo: b@x.de\r\nSubject: T\r\nDate: Tue, 08 Sep 2026 13:22:46 +0000\r\n"
            + kopf_teil).encode()


def test_textkoerper_mit_name_ist_kein_anhang():
    from app.ingest.eml_parse import parse_eml_message

    roh = _roh('Content-Type: text/plain; name="body.txt"\r\n\r\nHallo\r\n')

    assert eml_lesen(roh).anhaenge == []
    assert parse_eml_message(roh, "m")["hasAttachments"] is False


def test_html_alternative_mit_name_ist_kein_anhang():
    roh = _roh(
        'Content-Type: multipart/alternative; boundary="b"\r\n\r\n'
        '--b\r\nContent-Type: text/plain\r\n\r\nHallo\r\n'
        '--b\r\nContent-Type: text/html; name="mail.html"\r\n\r\n<p>Hallo</p>\r\n--b--\r\n'
    )

    assert eml_lesen(roh).anhaenge == []


def test_text_mit_attachment_disposition_ist_anhang():
    msg = _mail()
    msg.set_content("x")
    msg.add_attachment("Notiz", subtype="plain", filename="notiz.txt")

    assert [n for n, _ in eml_lesen(msg.as_bytes()).anhaenge] == ["notiz.txt"]


def test_inline_textanhang_mit_filename_ist_anhang_und_nicht_body():
    roh = _roh(
        'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
        '--b\r\nContent-Type: text/plain\r\n\r\nNormaler Body\r\n'
        '--b\r\nContent-Type: text/plain\r\nContent-Disposition: inline; filename="notiz.txt"\r\n\r\nNotiz-Inhalt\r\n'
        '--b\r\nContent-Type: text/csv\r\nContent-Disposition: inline; filename="daten.csv"\r\n\r\na,b\r\n--b--\r\n'
    )

    eml = eml_lesen(roh)

    assert [n for n, _ in eml.anhaenge] == ["notiz.txt", "daten.csv"]
    assert eml.text.endswith("Normaler Body")
    assert "Notiz-Inhalt" not in eml.text
