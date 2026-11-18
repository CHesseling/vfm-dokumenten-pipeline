"""LLM- und CLEF-Klassifikation je Dokument nebeneinander (fuer GUI und CLI)."""

from dataclasses import dataclass

from sqlmodel import Session, select

from app.enums import AnalyseArt, LaufStatus
from app.models import Analyse, Dokument, Lauf

ARTEN = (AnalyseArt.KLASSIFIKATION, AnalyseArt.KLASSIFIKATION_CLEF)


@dataclass(frozen=True)
class KlassErgebnis:
    modell: str
    kategorie: str
    sicherheit: float
    dauer_ms: int | None
    begruendung: str | None = None
    wahrscheinlichkeiten: list[tuple[str, float]] | None = None  # absteigend


@dataclass(frozen=True)
class KlassVergleich:
    dokument_id: int
    dateiname: str
    llm: KlassErgebnis | None
    clef: KlassErgebnis | None


def _dauern(session: Session, dokument_ids: list[int]) -> dict[tuple[int, str], int]:
    """Dauer des juengsten erfolgreichen Laufs je (Dokument, Schritt)."""
    laeufe = session.exec(
        select(Lauf)
        .where(Lauf.dokument_id.in_(dokument_ids), Lauf.status == LaufStatus.ERFOLG,
               Lauf.schritt.in_([f"analyse:{a.value}" for a in ARTEN]))
        .order_by(Lauf.id)
    ).all()
    return {(l.dokument_id, l.schritt): l.dauer_ms for l in laeufe}


def _ergebnis(analyse: Analyse | None, dauer: int | None) -> KlassErgebnis | None:
    if analyse is None:
        return None
    e = analyse.ergebnis
    wahrsch = e.get("wahrscheinlichkeiten")
    return KlassErgebnis(
        modell=analyse.modell,
        kategorie=e.get("kategorie", ""),
        sicherheit=float(e.get("sicherheit", 0.0)),
        dauer_ms=dauer,
        begruendung=e.get("begruendung"),
        wahrscheinlichkeiten=sorted(wahrsch.items(), key=lambda p: -p[1]) if wahrsch else None,
    )


def klassifikation_vergleich(session: Session, dokument_id: int | None = None) -> list[KlassVergleich]:
    """Alle Dokumente mit mindestens einer Klassifikation, sortiert nach ID."""
    abfrage = select(Analyse).where(Analyse.art.in_(ARTEN))
    if dokument_id is not None:
        abfrage = abfrage.where(Analyse.dokument_id == dokument_id)
    analysen = session.exec(abfrage).all()
    ids = sorted({a.dokument_id for a in analysen})
    if not ids:
        return []
    namen = {d.id: d.dateiname for d in session.exec(select(Dokument).where(Dokument.id.in_(ids))).all()}
    dauern = _dauern(session, ids)
    je = {(a.dokument_id, a.art): a for a in analysen}
    return [
        KlassVergleich(
            dokument_id=i,
            dateiname=namen.get(i, str(i)),
            llm=_ergebnis(je.get((i, AnalyseArt.KLASSIFIKATION)), dauern.get((i, "analyse:klassifikation"))),
            clef=_ergebnis(je.get((i, AnalyseArt.KLASSIFIKATION_CLEF)), dauern.get((i, "analyse:klassifikation_clef"))),
        )
        for i in ids
    ]
