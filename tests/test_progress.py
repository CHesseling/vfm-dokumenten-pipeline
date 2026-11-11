from app import progress


def test_lesen_unbekannter_id_gibt_none():
    assert progress.lesen(-1) is None


def test_starten_und_aktualisieren_baut_verlauf_auf():
    progress.starten(101)

    progress.aktualisieren(101, "Klassifiziere E-Mail...")
    progress.aktualisieren(101, "Verarbeite Tag 1/2...")

    status = progress.lesen(101)
    assert status.fertig is False
    assert status.schritt == "Verarbeite Tag 1/2..."
    assert [eintrag.text for eintrag in status.verlauf] == [
        "Klassifiziere E-Mail...",
        "Verarbeite Tag 1/2...",
    ]


def test_abschliessen_markiert_fertig_mit_ergebnis():
    progress.starten(102)

    progress.aktualisieren(102, "Klassifiziere E-Mail...")
    progress.abschliessen(102)

    status = progress.lesen(102)
    assert status.fertig is True
    assert status.fehler is None


def test_abschliessen_mit_fehler():
    progress.starten(103)

    progress.abschliessen(103, fehler="LLM nicht erreichbar")

    status = progress.lesen(103)
    assert status.fertig is True
    assert status.fehler == "LLM nicht erreichbar"


def test_aktualisieren_ohne_vorheriges_starten_legt_status_an():
    progress.aktualisieren(104, "Schritt ohne starten()")

    status = progress.lesen(104)
    assert status is not None
    assert status.schritt == "Schritt ohne starten()"


def test_zaehler_setzen_speichert_fortschritt():
    progress.starten("zaehler-test")

    progress.zaehler_setzen("zaehler-test", erledigt=3, gesamt=10, fehlgeschlagen=1)

    status = progress.lesen("zaehler-test")
    assert (status.erledigt, status.gesamt, status.fehlgeschlagen) == (3, 10, 1)


def test_abbruch_anfordern_wird_gelesen_und_beim_neustart_zurueckgesetzt():
    progress.starten("abbruch-test")
    assert progress.abbruch_angefordert("abbruch-test") is False

    progress.abbruch_anfordern("abbruch-test")
    assert progress.abbruch_angefordert("abbruch-test") is True

    progress.starten("abbruch-test")
    assert progress.abbruch_angefordert("abbruch-test") is False


def test_abbruch_angefordert_fuer_unbekannten_schluessel_ist_false():
    assert progress.abbruch_angefordert("gibt-es-nicht") is False
