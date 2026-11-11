"""In-Memory-Fortschrittsverfolgung fuer laenger laufende Verarbeitungen (z. B.
manueller Upload), die im Hintergrund-Thread statt im Request laufen. Die App
laeuft als ein einzelner uvicorn-Prozess (kein Multi-Worker-Setup, siehe
entrypoint.sh) - ein Prozess-globaler, durch ein Lock geschuetzter Dict reicht
daher aus. Bei einem Neustart geht der Status verloren, was bei einer laufenden
Verarbeitung ohnehin hinfaellig waere."""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ProgressEintrag:
    text: str
    zeitpunkt: datetime = field(default_factory=_jetzt)


@dataclass
class ProgressStatus:
    schritt: str = "Gestartet"
    begonnen_am: datetime = field(default_factory=_jetzt)
    aktualisiert_am: datetime = field(default_factory=_jetzt)
    fertig: bool = False
    fehler: str | None = None
    verlauf: list[ProgressEintrag] = field(default_factory=list)
    # Zaehler fuer Laeufe ueber viele Nachrichten (Watchfolder-Backfill) -
    # Grundlage fuer Fortschrittsbalken und Restzeit-Schaetzung.
    erledigt: int = 0
    gesamt: int = 0
    fehlgeschlagen: int = 0
    abbruch_angefordert: bool = False


# Schluessel ist entweder eine Email-ID (Upload-Fortschritt) oder ein fester
# String-Schluessel wie TICK_SCHLUESSEL (Fortschritt eines manuellen Abrufs
# ueber mehrere Nachrichten hinweg).
_lock = threading.Lock()
_status: dict[int | str, ProgressStatus] = {}


def starten(schluessel: int | str) -> None:
    with _lock:
        _status[schluessel] = ProgressStatus()


def aktualisieren(schluessel: int | str, schritt: str) -> None:
    with _lock:
        status = _status.setdefault(schluessel, ProgressStatus())
        status.schritt = schritt
        status.aktualisiert_am = _jetzt()
        status.verlauf.append(ProgressEintrag(text=schritt))


def zaehler_setzen(schluessel: int | str, erledigt: int, gesamt: int, fehlgeschlagen: int) -> None:
    with _lock:
        status = _status.setdefault(schluessel, ProgressStatus())
        status.erledigt = erledigt
        status.gesamt = gesamt
        status.fehlgeschlagen = fehlgeschlagen
        status.aktualisiert_am = _jetzt()


def abbruch_anfordern(schluessel: int | str) -> None:
    """Der Lauf prueft das Flag zwischen zwei Nachrichten - eine gerade
    laufende Verarbeitung wird nicht mittendrin abgebrochen."""
    with _lock:
        status = _status.get(schluessel)
        if status is not None and not status.fertig:
            status.abbruch_angefordert = True


def abbruch_angefordert(schluessel: int | str) -> bool:
    with _lock:
        status = _status.get(schluessel)
        return status is not None and status.abbruch_angefordert


def abschliessen(schluessel: int | str, fehler: str | None = None) -> None:
    with _lock:
        status = _status.setdefault(schluessel, ProgressStatus())
        status.fertig = True
        status.fehler = fehler
        status.aktualisiert_am = _jetzt()


def lesen(schluessel: int | str) -> ProgressStatus | None:
    with _lock:
        return _status.get(schluessel)
