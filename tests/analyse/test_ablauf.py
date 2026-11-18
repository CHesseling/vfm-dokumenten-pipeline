import io
import json

import httpx
import pytest
import respx
from PIL import Image
from sqlmodel import select

from app.analyse.ablauf import analyse_ausfuehren, bild_beschreiben, klassifizieren, zusammenfassen
from app.analyse.kategorien import Kategorie
from app.config import Settings
from app.enums import AnalyseArt, DokumentTyp, ExtraktionsMethode, LaufStatus
from app.models import Analyse, Dokument, Lauf, TextExtraktion
from app.providers.llm_client import LLMClient

CHAT = "http://chat/v1/chat/completions"
KATS = [Kategorie("Vertrag", "Verträge"), Kategorie("Sonstiges", "Rest")]


def _antwort(inhalt):
    return httpx.Response(200, json={"choices": [{"message": {"content": inhalt}}]})


@pytest.fixture
def s(tmp_path):
    k = tmp_path / "k.yaml"
    k.write_text("- name: Vertrag\n  beschreibung: Verträge\n- name: Sonstiges\n  beschreibung: Rest\n", encoding="utf-8")
    return Settings(
        database_url="postgresql+psycopg://x/y", daten_pfad=str(tmp_path / "daten"),
        chat_base_url="http://chat/v1", chat_model="chat-m", embed_base_url="http://e/v1", embed_model="e",
        rerank_backend="none", transcribe_backend="api", transcribe_base_url="http://t/v1",
        kategorien_pfad=str(k), _env_file=None,
    )


def _llm():
    return LLMClient("http://chat/v1", "chat-m")


def _dok(session, name, text, sha, typ=DokumentTyp.TEXT, aktiv=True):
    d = Dokument(sha256=sha, dateiname=name, typ=typ, mime="x/y", groesse=1)
    session.add(d)
    session.flush()
    if text is not None:
        session.add(TextExtraktion(dokument_id=d.id, methode=ExtraktionsMethode.TEXT, text=text, ist_aktiv=aktiv))
    session.commit()
    return d


@respx.mock
def test_zusammenfassen_kurz():
    route = respx.post(CHAT).mock(return_value=_antwort("Eine Zusammenfassung."))
    assert zusammenfassen(_llm(), "Kurzer Text") == {"text": "Eine Zusammenfassung."}
    assert route.call_count == 1


@respx.mock
def test_lange_texte_zweistufig(monkeypatch):
    import app.analyse.ablauf as ablauf

    monkeypatch.setattr(ablauf, "MAX_ZEICHEN", 100)
    # Teil-Zusammenfassungen sind so lang, dass ein Abschneiden bei MAX_ZEICHEN den letzten Abschnitt verlieren wuerde
    route = respx.post(CHAT).mock(side_effect=lambda req: _antwort("Teil" + "z" * 30))
    ablauf.zusammenfassen(_llm(), "x" * 300)  # 3 Abschnitte a 100 Zeichen
    assert route.call_count == 6  # 3 Abschnitte + 2 Gruppen + 1 Gesamt
    anzahl = route.call_count
    # Jede Ebene bekommt alle Teile (kein Abschneiden vor dem Gruppieren)
    assert "Abschnitt 3: Teilz" in "".join(c.request.content.decode() for c in list(route.calls)[3:])
    assert anzahl <= 3 + 3 * 3 + 1


@respx.mock
def test_zusammenfassung_terminiert_bei_langen_antworten(monkeypatch):
    import app.analyse.ablauf as ablauf

    monkeypatch.setattr(ablauf, "MAX_ZEICHEN", 100)
    route = respx.post(CHAT).mock(side_effect=lambda req: _antwort("e" * 80))
    ergebnis = ablauf.zusammenfassen(_llm(), "x" * 1000)  # 10 Abschnitte, jede Antwort 0.8*MAX
    assert ergebnis["gekuerzt"] is True
    assert route.call_count <= 10 + 3 * 10 + 1


@respx.mock
def test_sehr_lange_texte_dritte_ebene(monkeypatch):
    import app.analyse.ablauf as ablauf

    monkeypatch.setattr(ablauf, "MAX_ZEICHEN", 100)
    zaehler = iter(range(1, 1000))
    route = respx.post(CHAT).mock(side_effect=lambda req: _antwort(f"S{next(zaehler)}" + "z" * 30))
    ergebnis = ablauf.zusammenfassen(_llm(), "x" * 1000)  # 10 Abschnitte -> mehrere Ebenen
    assert ergebnis["text"].startswith("S")
    # Letzter Aufruf bekommt nur noch Eingaben, die in das Limit passen
    assert len(route.calls[-1].request.content.decode().split("Abschnitt 1:")[-1]) < 400
    # Jede Teil-Zusammenfassung der ersten Ebene (S1..S10) geht in eine Reduktion ein
    eingaben = "".join(c.request.content.decode() for c in list(route.calls)[10:])
    assert all(f"S{n}z" in eingaben for n in range(1, 11))


@respx.mock
def test_klassifizieren_gueltig():
    respx.post(CHAT).mock(return_value=_antwort(json.dumps(
        {"kategorie": "Vertrag", "begruendung": "Enthält Klauseln", "sicherheit": 0.9})))
    assert klassifizieren(_llm(), "Text", KATS) == {
        "kategorie": "Vertrag", "begruendung": "Enthält Klauseln", "sicherheit": 0.9}


@respx.mock
def test_unbekannte_kategorie_wird_sonstiges():
    respx.post(CHAT).mock(return_value=_antwort(json.dumps(
        {"kategorie": "Quatsch", "begruendung": "?", "sicherheit": 0.4})))
    e = klassifizieren(_llm(), "Text", KATS)
    assert e["kategorie"] == "Sonstiges" and e["roh_kategorie"] == "Quatsch"


@respx.mock
def test_klassifizieren_kuerzt_text():
    route = respx.post(CHAT).mock(return_value=_antwort(json.dumps(
        {"kategorie": "Vertrag", "begruendung": "b", "sicherheit": 1.0})))
    klassifizieren(_llm(), "y" * 50000, KATS)
    assert "y" * 12001 not in route.calls[0].request.content.decode()
    assert "y" * 12000 in route.calls[0].request.content.decode()


@respx.mock
def test_klassifizieren_nutzt_frage():
    route = respx.post(CHAT).mock(return_value=_antwort(json.dumps(
        {"kategorie": "Vertrag", "begruendung": "b", "sicherheit": 1.0})))
    klassifizieren(_llm(), "Text", KATS, frage="Was für ein Schriftstück ist das?")
    assert "Was für ein Schriftstück ist das?" in json.loads(route.calls[0].request.content)["messages"][0]["content"]


@respx.mock
def test_bild_beschreiben():
    route = respx.post(CHAT).mock(return_value=_antwort("Ein Hund im Park."))
    assert bild_beschreiben(_llm(), b"jpegdaten") == {"text": "Ein Hund im Park."}
    body = route.calls[0].request.content.decode()
    assert "image_url" in body and "identifizier" in body


@respx.mock
def test_bildbeschreibung_nur_fuer_bilder(session, s):
    _dok(session, "a.pdf", "Text", "1", typ=DokumentTyp.PDF)
    route = respx.post(CHAT).mock(return_value=_antwort("x"))
    analyse_ausfuehren(session, s, {AnalyseArt.BILDBESCHREIBUNG})
    assert route.call_count == 0
    assert len(session.exec(select(Analyse)).all()) == 0


@respx.mock
def test_leerer_text_keine_zusammenfassung(session, s):
    _dok(session, "leer.txt", "   ", "1")
    _dok(session, "ohne.txt", None, "2")
    route = respx.post(CHAT).mock(return_value=_antwort("x"))
    bilanz = analyse_ausfuehren(session, s, {AnalyseArt.ZUSAMMENFASSUNG, AnalyseArt.KLASSIFIKATION})
    assert route.call_count == 0 and len(session.exec(select(Analyse)).all()) == 0
    assert bilanz.erzeugt == 0


@respx.mock
def test_analyse_ersetzt_alte(session, s):
    d = _dok(session, "a.txt", "Hallo Welt", "1")
    respx.post(CHAT).mock(side_effect=[_antwort("Erste."), _antwort("Zweite.")])
    arten = {AnalyseArt.ZUSAMMENFASSUNG}
    b1 = analyse_ausfuehren(session, s, arten)
    b2 = analyse_ausfuehren(session, s, arten, dokument_id=d.id, nur_fehlende=False)
    zeilen = session.exec(select(Analyse)).all()
    assert len(zeilen) == 1 and zeilen[0].ergebnis == {"text": "Zweite."} and zeilen[0].modell == "chat-m"
    assert b1.erzeugt == 1 and b2.erzeugt == 1
    laeufe = session.exec(select(Lauf).where(Lauf.schritt == "analyse:zusammenfassung")).all()
    assert len(laeufe) == 2 and all(l.status == LaufStatus.ERFOLG for l in laeufe)


@respx.mock
def test_fehler_je_art_lauf_fehler_und_weiter(session, s):
    _dok(session, "a.txt", "Hallo", "1")
    # Reihenfolge: klassifikation (404), dann zusammenfassung
    respx.post(CHAT).mock(side_effect=[httpx.Response(404), _antwort("Kurz.")])
    bilanz = analyse_ausfuehren(session, s, {AnalyseArt.ZUSAMMENFASSUNG, AnalyseArt.KLASSIFIKATION})
    assert bilanz.fehler == 1 and bilanz.erzeugt == 1
    fehler = session.exec(select(Lauf).where(Lauf.status == LaufStatus.FEHLER)).one()
    assert fehler.schritt == "analyse:klassifikation" and "Modell nicht gefunden" in fehler.fehler
    assert session.exec(select(Analyse)).one().art == AnalyseArt.ZUSAMMENFASSUNG


@respx.mock
def test_bildbeschreibung_end_to_end(session, s):
    puffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(puffer, format="PNG")
    d = _dok(session, "b.png", "", "ab" + "0" * 62, typ=DokumentTyp.BILD)
    pfad = d.dateipfad(s.daten_pfad)
    pfad.parent.mkdir(parents=True)
    pfad.write_bytes(puffer.getvalue())
    respx.post(CHAT).mock(return_value=_antwort("Ein rotes Quadrat."))
    bilanz = analyse_ausfuehren(session, s, {AnalyseArt.BILDBESCHREIBUNG})
    assert bilanz.erzeugt == 1
    assert session.exec(select(Analyse)).one().ergebnis == {"text": "Ein rotes Quadrat."}


@respx.mock
def test_zweiter_lauf_rechnet_nichts_neu(session, s):
    _dok(session, "a.txt", "Ein Text zum Zusammenfassen.", "n1")
    route = respx.post(CHAT).mock(return_value=_antwort("Zusammenfassung."))
    arten = {AnalyseArt.ZUSAMMENFASSUNG}
    erster = analyse_ausfuehren(session, s, arten)
    assert erster.erzeugt == 1 and route.call_count == 1
    laeufe = len(session.exec(select(Lauf)).all())
    zweiter = analyse_ausfuehren(session, s, arten)
    assert zweiter.erzeugt == 0 and zweiter.vorhanden == 1
    assert route.call_count == 1  # 0 neue LLM-Calls
    assert len(session.exec(select(Lauf)).all()) == laeufe  # 0 neue Laeufe
    dritter = analyse_ausfuehren(session, s, arten, nur_fehlende=False)
    assert dritter.erzeugt == 1 and route.call_count == 2


def test_leerer_text_nur_einmal_protokolliert(session, s):
    _dok(session, "leer.txt", "   ", "n2")
    for _ in range(3):
        analyse_ausfuehren(session, s, {AnalyseArt.ZUSAMMENFASSUNG}, nur_fehlende=False)
    laeufe = session.exec(select(Lauf).where(Lauf.status == LaufStatus.UEBERSPRUNGEN)).all()
    assert len(laeufe) == 1


class ClefFake:
    def __init__(self, kategorie="Vertrag"):
        self.aufrufe = []
        self.kategorie = kategorie

    def klassifiziere(self, text, frage, kategorien):
        from app.providers.decisions import ClefAntwort

        self.aufrufe.append((text, frage, [k.name for k in kategorien]))
        return ClefAntwort(self.kategorie, 0.8, {"Vertrag": 0.8, "Sonstiges": 0.2})


def test_clef_klassifikation_gespeichert(session, s, monkeypatch):
    import app.analyse.ablauf as ablauf

    s.cortecs_api_key = "ck"
    fake = ClefFake()
    monkeypatch.setattr(ablauf, "classify_client", lambda s: fake)
    _dok(session, "a.txt", "z" * 20000, "1")
    bilanz = analyse_ausfuehren(session, s, {AnalyseArt.KLASSIFIKATION_CLEF})
    assert bilanz.erzeugt == 1
    analyse = session.exec(select(Analyse)).one()
    assert analyse.art == AnalyseArt.KLASSIFIKATION_CLEF and analyse.modell == "clef-flash:latest"
    assert analyse.ergebnis == {"kategorie": "Vertrag", "sicherheit": 0.8,
                                "wahrscheinlichkeiten": {"Vertrag": 0.8, "Sonstiges": 0.2}}
    text, frage, namen = fake.aufrufe[0]
    assert len(text) == 12000 and frage.startswith("Ordne das Dokument") and namen == ["Vertrag", "Sonstiges"]
    lauf = session.exec(select(Lauf).where(Lauf.schritt == "analyse:klassifikation_clef")).one()
    assert lauf.status == LaufStatus.ERFOLG and lauf.provider == "cortecs" and lauf.modell == "clef-flash:latest"


def test_clef_unbekannte_kategorie_wird_sonstiges(session, s, monkeypatch):
    import app.analyse.ablauf as ablauf

    s.cortecs_api_key = "ck"
    monkeypatch.setattr(ablauf, "classify_client", lambda s: ClefFake("Quatsch"))
    _dok(session, "a.txt", "Text", "1")
    analyse_ausfuehren(session, s, {AnalyseArt.KLASSIFIKATION_CLEF})
    e = session.exec(select(Analyse)).one().ergebnis
    assert e["kategorie"] == "Sonstiges" and e["roh_kategorie"] == "Quatsch"


@respx.mock
def test_clef_ohne_schluessel_still_aus(session, s, monkeypatch):
    import app.analyse.ablauf as ablauf

    monkeypatch.setattr(ablauf, "classify_client", lambda s: pytest.fail("CLEF ist aus"))
    respx.post(CHAT).mock(return_value=_antwort("Zusammenfassung."))
    _dok(session, "a.txt", "Text", "1")
    bilanz = analyse_ausfuehren(session, s, {AnalyseArt.ZUSAMMENFASSUNG, AnalyseArt.KLASSIFIKATION_CLEF})
    assert bilanz.erzeugt == 1 and bilanz.fehler == 0
    assert session.exec(select(Lauf).where(Lauf.schritt == "analyse:klassifikation_clef")).all() == []
