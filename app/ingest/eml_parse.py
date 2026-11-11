import base64
import email
import email.policy
import mimetypes
import re
from datetime import datetime, timezone
from email.message import Message
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser


_BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}
_IGNORIERTE_TAGS = {"style", "script", "head", "title"}


class _HtmlZuText(HTMLParser):
    """Wandelt HTML in Text um und erhaelt dabei Tabellen zeilenweise
    ("Zelle | Zelle | Zelle"). Die Pressestelle verschickt Tagesplaene als
    HTML-Tabelle (Kammer/Nummer/Beginn/Saal); im Klartext-Teil der Mail steht
    dann jede Zelle auf einer eigenen Zeile und die Spaltenzuordnung geht
    verloren. Verschachtelte (Layout-)Tabellen werden in die umgebende Zelle
    geschrieben."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ausgabe: list[str] = []
        # Pro offener Tabelle: (Zellen der aktuellen Zeile, Puffer der aktuellen Zelle oder None)
        self._tabellen: list[tuple[list[str], list[str] | None]] = []
        self._ignorieren = 0

    def _schreiben(self, text: str) -> None:
        for zellen, puffer in reversed(self._tabellen):
            if puffer is not None:
                puffer.append(text)
                return
        self._ausgabe.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in _IGNORIERTE_TAGS:
            self._ignorieren += 1
        elif tag == "table":
            self._schreiben("\n")
            self._tabellen.append(([], None))
        elif tag in ("td", "th") and self._tabellen:
            zellen, _ = self._tabellen[-1]
            self._tabellen[-1] = (zellen, [])
        elif tag in _BLOCK_TAGS:
            self._schreiben("\n")

    def handle_endtag(self, tag):
        if tag in _IGNORIERTE_TAGS:
            self._ignorieren = max(0, self._ignorieren - 1)
        elif tag in ("td", "th") and self._tabellen:
            zellen, puffer = self._tabellen[-1]
            if puffer is not None:
                zellen.append(" ".join("".join(puffer).split()))
            self._tabellen[-1] = (zellen, None)
        elif tag == "tr" and self._tabellen:
            self._zeile_abschliessen()
        elif tag == "table" and self._tabellen:
            self._zeile_abschliessen()
            self._tabellen.pop()
            self._schreiben("\n")
        elif tag in _BLOCK_TAGS:
            self._schreiben("\n")

    def _zeile_abschliessen(self) -> None:
        zellen, puffer = self._tabellen[-1]
        if puffer is not None:  # Zelle ohne schliessendes </td>
            zellen.append(" ".join("".join(puffer).split()))
        self._tabellen[-1] = ([], None)
        while zellen and not zellen[-1]:  # leere Zellen am Zeilenende sind nur Rauschen
            zellen.pop()
        if any(zellen):
            self._tabellen.pop()
            self._schreiben(" | ".join(zellen).rstrip() + "\n")
            self._tabellen.append(([], None))

    def handle_data(self, data):
        if self._tabellen and self._tabellen[-1][1] is None:
            return  # Leerraum zwischen <tr>/<td>-Tags (Quelltext-Einrueckung), kein Inhalt
        if not self._ignorieren:
            self._schreiben(re.sub(r"\s+", " ", data.replace("\xa0", " ")))

    def text(self) -> str:
        zeilen = [zeile.strip() for zeile in "".join(self._ausgabe).split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(zeilen)).strip()


def _html_zu_text(html_inhalt: str) -> str:
    parser = _HtmlZuText()
    parser.feed(html_inhalt)
    parser.close()
    return parser.text()


def _finde_body_text(msg: Message) -> str:
    if not msg.is_multipart():
        if msg.get_content_type() == "text/html":
            return _html_zu_text(msg.get_content())
        if msg.get_content_type() == "text/plain":
            return msg.get_content()
        return ""

    klartext_teil = None
    html_teil = None
    for teil in msg.walk():
        if teil.get_content_maintype() == "multipart":
            continue
        if _ist_anhang(teil):
            continue
        if teil.get_content_type() == "text/plain" and klartext_teil is None:
            klartext_teil = teil
        elif teil.get_content_type() == "text/html" and html_teil is None:
            html_teil = teil

    # Enthaelt die HTML-Version eine Tabelle, ist sie der bessere Text: nur dort
    # bleibt die Zeilen-/Spaltenstruktur erhalten (siehe _HtmlZuText).
    if html_teil is not None and re.search(r"<table", html_teil.get_content(), re.IGNORECASE):
        return _html_zu_text(html_teil.get_content())
    if klartext_teil is not None:
        return klartext_teil.get_content()
    if html_teil is not None:
        return _html_zu_text(html_teil.get_content())
    return ""


def _empfaenger(msg: Message, kopfzeile: str) -> list[dict]:
    adressen = getaddresses([str(wert) for wert in msg.get_all(kopfzeile, [])])
    return [{"emailAddress": {"address": adresse}} for _, adresse in adressen if adresse]


def parse_eml_message(eml_bytes: bytes, message_id: str) -> dict:
    """Parst eine hochgeladene .eml-Datei in ein Graph-API-Message-Dict
    (dieselbe Form, die store_email_if_new/store_attachments erwarten),
    damit Upload- und Poll-Pfad dieselbe Pipeline durchlaufen koennen."""
    msg = email.message_from_bytes(eml_bytes, policy=email.policy.default)
    _, absender_adresse = parseaddr(msg.get("From", ""))
    betreff = msg.get("Subject", "")

    datum_header = msg.get("Date")
    empfangen = parsedate_to_datetime(datum_header) if datum_header else datetime.now(timezone.utc)
    if empfangen.tzinfo is None:
        empfangen = empfangen.replace(tzinfo=timezone.utc)

    hat_anhaenge = any(_ist_anhang(teil) for teil in msg.walk())

    return {
        "id": message_id,
        "receivedDateTime": empfangen.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "from": {"emailAddress": {"address": absender_adresse}},
        "toRecipients": _empfaenger(msg, "To"),
        "ccRecipients": _empfaenger(msg, "Cc"),
        "subject": betreff,
        "body": {"contentType": "text", "content": _finde_body_text(msg)},
        "hasAttachments": hat_anhaenge,
    }


def _ist_anhang(teil: Message) -> bool:
    if teil.get_content_maintype() == "multipart":
        return False
    if teil.get_content_type() == "message/rfc822":
        return True
    if teil.get_content_disposition() == "attachment":
        return True
    # Textteile sind Mailkoerper - Anhang nur mit Content-Disposition (inline
    # oder attachment), die einen filename traegt; name= im Content-Type zaehlt nicht.
    if teil.get_content_maintype() == "text":
        return bool(teil.get_param("filename", header="content-disposition"))
    # Inline (oder ohne Disposition) nur mit Dateiname; Signatur-/Logobilder
    # (image/* mit Content-ID) und reine Textkoerper zaehlen nicht.
    if not teil.get_filename():
        return False
    return not (teil.get_content_maintype() == "image" and teil.get("Content-ID"))


def extract_eml_attachments(eml_bytes: bytes) -> list[dict]:
    """Extrahiert Anhaenge einer .eml-Datei als Graph-API-Attachment-Dicts
    (dieselbe Form, die store_attachments erwartet)."""
    msg = email.message_from_bytes(eml_bytes, policy=email.policy.default)
    anhaenge = []
    namenlos = 0
    for teil in msg.walk():
        if not _ist_anhang(teil):
            continue
        dateiname = teil.get_filename()
        if teil.get_content_type() == "message/rfc822":
            eingebettet = teil.get_payload(0)
            inhalt = eingebettet.as_bytes()
            if not dateiname:
                dateiname = f"{(eingebettet.get('Subject') or 'weitergeleitet').strip()}.eml"
        else:
            inhalt = teil.get_content()
            if isinstance(inhalt, str):
                inhalt = inhalt.encode("utf-8")
        if not dateiname:
            namenlos += 1
            endung = mimetypes.guess_extension(teil.get_content_type()) or ".bin"
            dateiname = f"anhang-{namenlos}{endung}"
        anhaenge.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": dateiname,
                "contentBytes": base64.b64encode(inhalt).decode("ascii"),
            }
        )
    return anhaenge
