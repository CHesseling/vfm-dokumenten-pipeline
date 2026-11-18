from app.analyse.vergleich import klassifikation_vergleich
from app.enums import AnalyseArt, DokumentTyp, LaufStatus
from app.models import Analyse, Dokument, Lauf

LLM = {"kategorie": "Vertrag", "begruendung": "Klauseln", "sicherheit": 0.9}
CLEF = {"kategorie": "Rechnung", "sicherheit": 0.7, "wahrscheinlichkeiten": {"Vertrag": 0.3, "Rechnung": 0.7}}


def _dok(session, name, sha):
    d = Dokument(sha256=sha, dateiname=name, typ=DokumentTyp.TEXT, mime="text/plain", groesse=1)
    session.add(d)
    session.flush()
    return d


def _analyse(session, d, art, modell, ergebnis, *dauern):
    session.add(Analyse(dokument_id=d.id, art=art, modell=modell, ergebnis=ergebnis))
    for ms in dauern:
        session.add(Lauf(schritt=f"analyse:{art.value}", dokument_id=d.id, provider="p", modell=modell,
                         dauer_ms=ms, status=LaufStatus.ERFOLG))


def test_vergleich_nebeneinander(session):
    a = _dok(session, "a.txt", "1")
    b = _dok(session, "b.txt", "2")
    _dok(session, "leer.txt", "3")  # ohne Klassifikation: taucht nicht auf
    _analyse(session, a, AnalyseArt.KLASSIFIKATION, "chat-m", LLM, 5000, 4200)
    _analyse(session, a, AnalyseArt.KLASSIFIKATION_CLEF, "clef-flash:latest", CLEF, 120)
    _analyse(session, b, AnalyseArt.KLASSIFIKATION, "chat-m", LLM)
    session.commit()
    zeilen = klassifikation_vergleich(session)
    assert [z.dateiname for z in zeilen] == ["a.txt", "b.txt"]
    za, zb = zeilen
    assert za.llm.kategorie == "Vertrag" and za.llm.sicherheit == 0.9 and za.llm.dauer_ms == 4200  # juengster Lauf
    assert za.llm.begruendung == "Klauseln" and za.llm.modell == "chat-m"
    assert za.clef.kategorie == "Rechnung" and za.clef.dauer_ms == 120
    assert za.clef.wahrscheinlichkeiten == [("Rechnung", 0.7), ("Vertrag", 0.3)]  # absteigend
    assert zb.clef is None and zb.llm.dauer_ms is None
    assert [z.dateiname for z in klassifikation_vergleich(session, dokument_id=b.id)] == ["b.txt"]
