"""Muster-NER: IBAN, Telefon, E-Mail, Geldbetrag, Datum - regelbasiert, ohne Modell."""

import re
from decimal import Decimal, InvalidOperation

import dateparser
import phonenumbers
from schwifty import IBAN

from app.ner.treffer import Treffer

# Bei gleich langen, ueberlappenden Treffern gewinnt das frueher genannte Label.
_VORRANG = ("iban", "email", "telefon", "geldbetrag", "datum")

_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Za-z0-9])")
_IBAN_GRUPPE = re.compile(r" ?[A-Z0-9]{1,4}$")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

_ZAHL = r"(?:\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)"
_LINKS = r"(?<![\d.,])"
_GELD_NACH = re.compile(rf"{_LINKS}({_ZAHL})\s?(?:€|EUR|Euro)(?!\w)")
_GELD_VOR = re.compile(rf"(?<!\w)(?:€|EUR)\s?({_ZAHL})(?![\d]|[.,]\d)")

_MONATE = (
    "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
)
_DATUM = [
    re.compile(r"(?<![\d.])\d{1,2}\.\d{1,2}\.\d{2,4}(?!\d)"),
    re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"),
    re.compile(rf"(?<!\d)\d{{1,2}}\.\s?(?:{_MONATE})\s\d{{4}}(?!\d)"),
]


def _iban_treffer(text: str) -> list[Treffer]:
    treffer = []
    for m in _IBAN.finditer(text):
        kandidat = m.group()
        # Zu gierige Kandidaten (angehaengte Folgewoerter in Grossbuchstaben) kuerzen
        while kandidat:
            try:
                iban = IBAN(kandidat.replace(" ", ""))
            except ValueError:
                gekuerzt = _IBAN_GRUPPE.sub("", kandidat, count=1)
                if gekuerzt == kandidat:
                    break
                kandidat = gekuerzt
                continue
            treffer.append(
                Treffer("iban", kandidat, m.start(), m.start() + len(kandidat), iban.compact, 1.0)
            )
            break
    return treffer


def _telefon_treffer(text: str) -> list[Treffer]:
    return [
        Treffer(
            "telefon",
            m.raw_string,
            m.start,
            m.end,
            phonenumbers.format_number(m.number, phonenumbers.PhoneNumberFormat.E164),
            1.0,
        )
        for m in phonenumbers.PhoneNumberMatcher(text, "DE", leniency=phonenumbers.Leniency.VALID)
    ]


def _email_treffer(text: str) -> list[Treffer]:
    return [Treffer("email", m.group(), m.start(), m.end(), m.group().lower(), 1.0) for m in _EMAIL.finditer(text)]


def _betrag(zahl: str) -> str | None:
    try:
        wert = Decimal(zahl.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None
    return f"{wert:.2f} EUR"


def _geld_treffer(text: str) -> list[Treffer]:
    treffer = []
    for muster in (_GELD_NACH, _GELD_VOR):
        for m in muster.finditer(text):
            treffer.append(Treffer("geldbetrag", m.group(), m.start(), m.end(), _betrag(m.group(1)), 1.0))
    return treffer


def _datum_treffer(text: str) -> list[Treffer]:
    treffer = []
    for muster in _DATUM:
        for m in muster.finditer(text):
            geparst = dateparser.parse(
                m.group(), languages=["de"], settings={"DATE_ORDER": "DMY", "STRICT_PARSING": True}
            )
            norm = geparst.date().isoformat() if geparst else None
            treffer.append(Treffer("datum", m.group(), m.start(), m.end(), norm, 1.0))
    return treffer


def finde_muster(text: str) -> list[Treffer]:
    geld_und_datum = _geld_treffer(text) + _datum_treffer(text)
    # Zahlenfolgen wie "03.03.2024" erkennt der Telefon-Matcher als Rufnummer: Telefon-
    # Treffer, die ein Datum oder einen Betrag beruehren, sind keine Telefonnummern.
    telefone = [
        t
        for t in _telefon_treffer(text)
        if all(t.ende <= g.start or t.start >= g.ende for g in geld_und_datum)
    ]
    kandidaten = _iban_treffer(text) + telefone + _email_treffer(text) + geld_und_datum
    # Laengster Treffer gewinnt, bei Gleichstand das Label mit Vorrang.
    kandidaten.sort(key=lambda t: (-(t.ende - t.start), _VORRANG.index(t.label), t.start))
    behalten: list[Treffer] = []
    for t in kandidaten:
        if all(t.ende <= b.start or t.start >= b.ende for b in behalten):
            behalten.append(t)
    return sorted(behalten, key=lambda t: t.start)


_FINDER = {
    "iban": _iban_treffer,
    "telefon": _telefon_treffer,
    "email": _email_treffer,
    "geldbetrag": _geld_treffer,
    "datum": _datum_treffer,
}


def normalisiere(label: str, text: str) -> str | None:
    """Normalform wie bei finde_muster (None fuer person/organisation/ort oder wenn nicht normalisierbar)."""
    finder = _FINDER.get(label)
    if finder is None:
        return None
    wert = text.strip()
    for t in finder(wert):
        if t.start == 0 and t.ende == len(wert):
            return t.normalisiert
    return None
