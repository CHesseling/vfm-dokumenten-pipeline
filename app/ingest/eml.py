"""E-Mail (.eml) lesen: Kopfdaten, Text und Anhaenge."""

import base64
from dataclasses import dataclass, field

from app.ingest.eml_parse import extract_eml_attachments, parse_eml_message


@dataclass
class EmlInhalt:
    metadaten: dict
    text: str
    anhaenge: list[tuple[str, bytes]] = field(default_factory=list)


def eml_lesen(inhalt: bytes) -> EmlInhalt:
    nachricht = parse_eml_message(inhalt, message_id="eml")
    empfaenger = [
        r["emailAddress"]["address"]
        for r in nachricht.get("toRecipients", []) + nachricht.get("ccRecipients", [])
    ]
    metadaten = {
        "absender": nachricht["from"]["emailAddress"]["address"],
        "empfaenger": empfaenger,
        "betreff": nachricht["subject"],
        "datum": nachricht["receivedDateTime"],
    }
    kopf = (
        f"Von: {metadaten['absender']}\n"
        f"An: {', '.join(empfaenger)}\n"
        f"Datum: {metadaten['datum']}\n"
        f"Betreff: {metadaten['betreff']}"
    )
    text = f"{kopf}\n\n{nachricht['body']['content']}".rstrip()
    anhaenge = [(a["name"], base64.b64decode(a["contentBytes"])) for a in extract_eml_attachments(inhalt)]
    return EmlInhalt(metadaten=metadaten, text=text, anhaenge=anhaenge)
