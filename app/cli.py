"""`vfm` - Kommandozeile fuer alle Pipeline-Schritte des Workshops."""

import functools
from typing import Optional

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from sqlalchemy import distinct, func, select
from sqlmodel import Session

from app.config import Settings, lade_settings
from app.db import get_engine
from app.enums import DokumentTyp
from app.providers.llm_client import ProviderFehler

app = typer.Typer(help="Workshop-Pipeline: Dokumente einlesen, auswerten, durchsuchen.", no_args_is_help=True)
konsole = Console()
fehlerkonsole = Console(stderr=False)


@app.callback()
def hauptoption(
    ctx: typer.Context,
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="Anbieter-Profil: ollama oder cortecs (Standard: PROVIDER aus .env)."
    ),
) -> None:
    if isinstance(ctx.obj, Settings):  # bereits injiziert (Tests)
        return
    try:
        ctx.obj = lade_settings(provider)
    except ValidationError as fehler:
        felder = ", ".join(str(e["loc"][0]).upper() for e in fehler.errors())
        fehlerkonsole.print(
            f"[red]Konfiguration unvollständig – es fehlen oder sind ungültig: {escape(felder)}. "
            "Bitte .env und profile/*.env prüfen.[/red]"
        )
        raise typer.Exit(2)
    except ValueError as fehler:
        fehlerkonsole.print(f"[red]{escape(str(fehler))}[/red]")
        raise typer.Exit(2)


def cli_fehler(funktion):
    """Faengt ProviderFehler: rot ausgeben, Exit-Code 2, kein Traceback."""

    @functools.wraps(funktion)
    def huelle(*args, **kwargs):
        try:
            return funktion(*args, **kwargs)
        except ProviderFehler as fehler:
            fehlerkonsole.print(f"[red]Fehler – {escape(str(fehler))}[/red]", highlight=False)
            raise typer.Exit(2)

    return huelle


def session_aus(s: Settings) -> Session:
    return Session(get_engine(s.database_url))


@app.command()
@cli_fehler
def check(ctx: typer.Context) -> None:
    """Prueft, ob alle Modell-Rollen (Chat, Vision, Embedding, Rerank, Transkription) erreichbar sind."""
    from app.providers.check import pruefe_rollen

    s: Settings = ctx.obj
    konsole.print(f"Provider-Profil: [bold]{s.provider}[/bold]")
    tabelle = Table("Rolle", "Backend", "Modell", "Status", "Details")
    ergebnisse = pruefe_rollen(s)
    for e in ergebnisse:
        status = "[green]OK[/green]" if e.ok else "[red]FEHLER[/red]"
        tabelle.add_row(*(escape(x) for x in (e.rolle, e.backend, e.modell)), status, escape(e.detail))
    konsole.print(tabelle)
    if not all(e.ok for e in ergebnisse):
        konsole.print("[red]Mindestens eine Rolle ist nicht einsatzbereit.[/red]")
        raise typer.Exit(1)


@app.command()
@cli_fehler
def status(ctx: typer.Context) -> None:
    """Zeigt, wie weit die Dokumente je Typ verarbeitet sind."""
    from app.statistik import STUFEN, zaehlerstaende

    s: Settings = ctx.obj
    with session_aus(s) as session:
        zahlen = zaehlerstaende(session, s)

    tabelle = Table("Typ", "Dokumente", "mit aktivem Text", "mit Entitäten", "mit Embeddings (aktuelles Modell)", "mit Analyse")
    for typ in DokumentTyp:
        tabelle.add_row(
            typ.value,
            *(str(zahlen[stufe].get(typ, 0)) for stufe in STUFEN),
        )
    konsole.print(tabelle)


@app.command()
@cli_fehler
def ingest(
    ctx: typer.Context,
    pfad: str = typer.Argument(..., help="Datei oder Ordner mit Rechercheunterlagen."),
    methode: str = typer.Option(
        "schnell",
        "--methode",
        "-m",
        help="PDF-Methode: schnell, docling, vision oder alle. Bei anderen Dateitypen ohne Wirkung. "
        "Standard: schnell (Docling kommt automatisch dazu, wenn kaum Text gefunden wird).",
    ),
) -> None:
    """Liest Dateien ein (PDF, Mail, Audio, Bild, Text) und extrahiert Text."""
    from pathlib import Path

    from rich.progress import BarColumn, Progress, TextColumn

    from app.ingest.ablauf import dateien_finden, ingest_clients, ingest_ordner

    s: Settings = ctx.obj
    if methode not in ("schnell", "docling", "vision", "alle"):
        fehlerkonsole.print("[red]Unbekannte Methode – erlaubt: schnell, docling, vision, alle[/red]")
        raise typer.Exit(2)
    ziel = Path(pfad)
    if not ziel.exists():
        fehlerkonsole.print(f"[red]Pfad nicht gefunden: {escape(pfad)}[/red]")
        raise typer.Exit(1)
    methoden = None if methode == "schnell" else {methode}
    with session_aus(s) as session, Progress(
        TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
        console=konsole,
    ) as fortschritt:
        aufgabe = fortschritt.add_task("", total=len(dateien_finden(ziel)))

        def bei_datei(nr: int, gesamt: int, name: str) -> None:
            fortschritt.update(aufgabe, completed=nr - 1, total=gesamt, description=escape(name))

        bilanz = ingest_ordner(
            session, ziel, s, ingest_clients(s), methoden=methoden, bei_datei=bei_datei
        )
        fortschritt.update(aufgabe, completed=fortschritt.tasks[0].total, description="fertig")
    konsole.print(f"neu: {bilanz.neu}, bekannt: {bilanz.bekannt}, fehler: {bilanz.fehler}")


@app.command()
@cli_fehler
def text(
    ctx: typer.Context,
    dokument_id: int = typer.Argument(..., metavar="ID", help="Dokument-ID."),
    vergleich: bool = typer.Option(False, "--vergleich", help="Alle Extraktionsmethoden nebeneinander."),
    aktiv: Optional[str] = typer.Option(None, "--aktiv", help="Methode als aktiv setzen."),
) -> None:
    """Zeigt den aktiven Text eines Dokuments oder vergleicht die Methoden."""
    from app.ingest.speichern import aktiv_setzen
    from app.models import Dokument, TextExtraktion

    s: Settings = ctx.obj
    with session_aus(s) as session:
        if session.get(Dokument, dokument_id) is None:
            fehlerkonsole.print(f"[red]Dokument {dokument_id} nicht gefunden.[/red]")
            raise typer.Exit(1)
        extraktionen = session.exec(
            select(TextExtraktion).where(TextExtraktion.dokument_id == dokument_id).order_by(TextExtraktion.id)
        ).scalars().all()
        if aktiv is not None:
            ziel = next((e for e in extraktionen if e.methode.value == aktiv), None)
            if ziel is None:
                fehlerkonsole.print(f"[red]Keine Extraktion mit Methode '{escape(aktiv)}' vorhanden.[/red]")
                raise typer.Exit(1)
            aktiv_setzen(session, ziel.id, s)
            session.commit()
            session.expire_all()
            extraktionen = session.exec(
                select(TextExtraktion).where(TextExtraktion.dokument_id == dokument_id).order_by(TextExtraktion.id)
            ).scalars().all()
        if vergleich:
            tabelle = Table("Methode", "Zeichen", "Dauer", "Modell", "Anfang")
            for e in extraktionen:
                marke = "*" if e.ist_aktiv else ""
                tabelle.add_row(
                    escape(e.methode.value + marke),
                    str(len(e.text)),
                    f"{e.dauer_ms} ms",
                    escape(e.modell or "-"),
                    escape(e.text[:300]),
                )
            konsole.print(tabelle)
            return
        aktive = next((e for e in extraktionen if e.ist_aktiv), None)
        if aktive is None:
            fehlerkonsole.print(f"[red]Dokument {dokument_id} hat noch keinen Text.[/red]")
            raise typer.Exit(1)
        konsole.print(escape(aktive.text), highlight=False)


@app.command()
@cli_fehler
def sql(
    ctx: typer.Context,
    abfrage: str = typer.Argument(..., help="SQL-Abfrage (nur lesend)."),
    limit: int = typer.Option(500, "--limit", "-l", help="Höchstzahl der Zeilen."),
) -> None:
    """Fuehrt eine schreibgeschuetzte SQL-Abfrage aus und zeigt das Ergebnis als Tabelle."""
    from app.sql.abfrage import SqlFehler, lese_engine, sql_ausfuehren, zelle_text

    s: Settings = ctx.obj
    try:
        ergebnis = sql_ausfuehren(lese_engine(s), abfrage, limit=limit)
    except SqlFehler as fehler:
        fehlerkonsole.print(f"[red]{escape(str(fehler))}[/red]", highlight=False)
        raise typer.Exit(1)
    tabelle = Table(*(escape(sp) for sp in ergebnis.spalten))
    for zeile in ergebnis.zeilen:
        tabelle.add_row(*(escape(zelle_text(w)) for w in zeile))
    konsole.print(tabelle)
    konsole.print(f"{len(ergebnis.zeilen)} Zeilen in {ergebnis.dauer_ms} ms")
    if ergebnis.abgeschnitten:
        konsole.print(f"[yellow]Ergebnis abgeschnitten: nur die ersten {limit} Zeilen.[/yellow]")


@app.command()
@cli_fehler
def ner(
    ctx: typer.Context,
    methode: str = typer.Option(
        "standard",
        "--methode",
        "-m",
        help="gliner, muster, llm oder alle (Standard: gliner + muster; das LLM ist langsamer und wird nur auf Wunsch genutzt).",
    ),
    dokument: Optional[int] = typer.Option(None, "--dokument", "-d", help="Nur dieses Dokument (ID)."),
    labels: Optional[str] = typer.Option(None, "--labels", help="Kommagetrennte Labels, z. B. person,iban."),
    vergleich: bool = typer.Option(False, "--vergleich", help="Methoden nebeneinander (braucht --dokument)."),
) -> None:
    """Erkennt Entitäten (Personen, Orte, IBAN, ...) mit Mustern, GliNER und/oder LLM."""
    from rich.progress import BarColumn, Progress, TextColumn

    from app.enums import NerMethode
    from app.models import TextExtraktion
    from app.ner.ablauf import ner_ausfuehren, vergleich as ner_vergleich
    from app.ner.treffer import LABELS

    s: Settings = ctx.obj
    if methode == "standard":
        methoden = {NerMethode.GLINER, NerMethode.MUSTER}
    elif methode == "alle":
        methoden = set(NerMethode)
    elif methode in {m.value for m in NerMethode}:
        methoden = {NerMethode(methode)}
    else:
        fehlerkonsole.print("[red]Unbekannte Methode – erlaubt: gliner, muster, llm, alle[/red]")
        raise typer.Exit(2)
    if vergleich and dokument is None:
        fehlerkonsole.print("[red]--vergleich braucht --dokument ID[/red]")
        raise typer.Exit(2)
    label_liste = None
    if labels:
        label_liste = [l.strip() for l in labels.split(",") if l.strip()]
        unbekannt = [l for l in label_liste if l not in LABELS]
        if unbekannt:
            fehlerkonsole.print(
                f"[red]Unbekannte Labels: {escape(', '.join(unbekannt))} – erlaubt: {escape(', '.join(LABELS))}[/red]"
            )
            raise typer.Exit(2)
    with session_aus(s) as session:
        with Progress(
            TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
            console=konsole,
        ) as fortschritt:
            aufgabe = fortschritt.add_task("", total=None)

            def bei_dokument(nr: int, gesamt: int, name: str) -> None:
                fortschritt.update(aufgabe, completed=nr - 1, total=gesamt, description=escape(name))

            bilanz = ner_ausfuehren(
                session, s, methoden, dokument_id=dokument, labels=label_liste, bei_dokument=bei_dokument
            )
        konsole.print(
            f"Dokumente: {bilanz.dokumente}, Entitäten: {bilanz.entitaeten}, "
            f"übersprungen: {bilanz.uebersprungen}, Fehler: {bilanz.fehler}"
        )
        if vergleich:
            extraktion = session.exec(
                select(TextExtraktion).where(TextExtraktion.dokument_id == dokument, TextExtraktion.ist_aktiv.is_(True))
            ).scalars().first()
            if extraktion is None:
                fehlerkonsole.print(f"[red]Dokument {dokument} hat keinen aktiven Text.[/red]")
                raise typer.Exit(1)
            spalten = sorted(m.value for m in methoden)
            tabelle = Table("Label", "Text", *spalten)
            for z in ner_vergleich(session, extraktion.id):
                tabelle.add_row(escape(z.label), escape(z.text_normalisiert), *("✓" if m in z.methoden else "" for m in spalten))
            konsole.print(tabelle)
    if bilanz.fehler:
        konsole.print("[yellow]Mindestens eine Methode ist fehlgeschlagen – Details in den Läufen (Dokument-Seite).[/yellow]")


@app.command()
@cli_fehler
def embed(
    ctx: typer.Context,
    alle_neu: bool = typer.Option(False, "--alle-neu", help="Vorhandene Embeddings des aktuellen Modells neu berechnen."),
) -> None:
    """Erzeugt Embeddings für alle Textabschnitte (Chunks) mit dem aktuellen Embedding-Modell."""
    from rich.progress import BarColumn, Progress, TextColumn

    from app.embed.index import embed_ausfuehren, vorhandene_modelle
    from app.providers.factory import embedding_client

    s: Settings = ctx.obj
    client = embedding_client(s)
    with session_aus(s) as session:
        with Progress(
            TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
            console=konsole,
        ) as fortschritt:
            aufgabe = fortschritt.add_task("Embeddings", total=None)

            def bei_fortschritt(nr: int, gesamt: int) -> None:
                fortschritt.update(aufgabe, completed=nr, total=gesamt)

            bilanz = embed_ausfuehren(
                session, client, nur_fehlende=not alle_neu, bei_fortschritt=bei_fortschritt, provider=s.provider
            )
        konsole.print(
            f"Modell: [bold]{escape(client.model)}[/bold], Dimension: {bilanz.dimension or '-'}, "
            f"neu: {bilanz.neu}, bereits vorhanden: {bilanz.vorhanden}"
        )
        tabelle = Table("Modell", "Embeddings")
        for modell, anzahl in vorhandene_modelle(session):
            tabelle.add_row(escape(modell), str(anzahl))
        konsole.print(tabelle)


def _suche_tabelle(treffer, mit_rerank: bool, volltext: bool) -> Table:
    if volltext:
        tabelle = Table("Rang", "Dokument", "Ausschnitt")
        for nr, t in enumerate(treffer, 1):
            ausschnitt = escape((t.snippet or t.text[:200]).replace("<b>", "").replace("</b>", ""))
            tabelle.add_row(str(nr), escape(f"{t.dateiname} (#{t.dokument_id})"), ausschnitt)
        return tabelle
    spalten = ["Rang", "Vektor-Rang → Rerank-Rang" if mit_rerank else "Vektor-Rang", "Vektor-Score"]
    if mit_rerank:
        spalten.append("Rerank-Score")
    tabelle = Table(*spalten, "Dokument", "Ausschnitt")
    for nr, t in enumerate(treffer, 1):
        rang = f"{t.vektor_rang} → {t.rerank_rang}" if mit_rerank else str(t.vektor_rang)
        zellen = [str(nr), rang, f"{t.vektor_score:.3f}"]
        if mit_rerank:
            zellen.append(f"{t.rerank_score:.3f}")
        tabelle.add_row(*zellen, escape(f"{t.dateiname} (#{t.dokument_id})"), escape(t.text[:200].replace("\n", " ")))
    return tabelle


@app.command()
@cli_fehler
def suche(
    ctx: typer.Context,
    anfrage: str = typer.Argument(..., help="Suchanfrage."),
    volltext: bool = typer.Option(False, "--volltext", help="Volltextsuche statt semantischer Suche."),
    top_n: Optional[int] = typer.Option(None, "--top-n", help="Vektor-Kandidaten (Standard: RAG_TOP_N)."),
    top_k: Optional[int] = typer.Option(None, "--top-k", help="Ergebnisse (Standard: RAG_TOP_K)."),
    ohne_rerank: bool = typer.Option(False, "--ohne-rerank", help="Reihenfolge der Vektorsuche beibehalten."),
) -> None:
    """Durchsucht die Textabschnitte: Volltext oder semantisch (mit Rerank)."""
    from app.embed.suche import KeineEmbeddingsFehler, semantische_suche, volltext_suche
    from app.providers.factory import embedding_client, reranker
    from app.providers.rerank import KeinReranker

    s: Settings = ctx.obj
    with session_aus(s) as session:
        if volltext:
            treffer = volltext_suche(session, anfrage, limit=top_k or s.rag_top_k)
            mit_rerank = False
        else:
            rr = KeinReranker() if ohne_rerank else reranker(s)
            mit_rerank = not isinstance(rr, KeinReranker)
            try:
                treffer = semantische_suche(
                    session, anfrage, embedding_client(s), rr, top_n or s.rag_top_n, top_k or s.rag_top_k
                )
            except KeineEmbeddingsFehler as fehler:
                fehlerkonsole.print(f"[red]{escape(str(fehler))}[/red]", highlight=False)
                raise typer.Exit(1)
    if not treffer:
        konsole.print("Keine Treffer.")
        return
    konsole.print(_suche_tabelle(treffer, mit_rerank, volltext))


@app.command()
@cli_fehler
def frage(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Frage an die Dokumente."),
    top_k: Optional[int] = typer.Option(None, "--top-k", help="Anzahl Quellen (Standard: RAG_TOP_K)."),
) -> None:
    """Beantwortet eine Frage anhand der Dokumente (RAG) mit Quellenangaben."""
    from app.embed.rag import antwort_erzeugen
    from app.embed.suche import KeineEmbeddingsFehler, semantische_suche
    from app.providers.factory import chat_client, embedding_client, reranker

    s: Settings = ctx.obj
    with session_aus(s) as session:
        try:
            treffer = semantische_suche(
                session, text, embedding_client(s), reranker(s), s.rag_top_n, top_k or s.rag_top_k
            )
        except KeineEmbeddingsFehler as fehler:
            fehlerkonsole.print(f"[red]{escape(str(fehler))}[/red]", highlight=False)
            raise typer.Exit(1)
    antwort = antwort_erzeugen(chat_client(s), text, treffer)
    konsole.print(escape(antwort.text), highlight=False)
    if antwort.quellen:
        tabelle = Table("Nr.", "Dateiname", "Dokument-ID")
        for n, t in enumerate(antwort.quellen, 1):
            tabelle.add_row(f"[{n}]".replace("[", "\\["), escape(t.dateiname), str(t.dokument_id))
        konsole.print(tabelle)


ANALYSE_ARTEN = ("zusammenfassung", "klassifikation", "bildbeschreibung", "alle")


def _analyse_stufe(session: Session, s: Settings, arten, dokument: Optional[int] = None):
    """Analyse mit Fortschrittsbalken; gibt die AnalyseBilanz zurueck."""
    from rich.progress import BarColumn, Progress, TextColumn

    from app.analyse import ablauf

    with Progress(
        TextColumn("{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
        console=konsole,
    ) as fortschritt:
        aufgabe = fortschritt.add_task("", total=None)

        def bei_dokument(nr: int, gesamt: int, name: str) -> None:
            fortschritt.update(aufgabe, completed=nr - 1, total=gesamt, description=escape(name))

        return ablauf.analyse_ausfuehren(session, s, arten, dokument_id=dokument, bei_dokument=bei_dokument)


def _analyse_zeile(bilanz) -> str:
    return (
        f"Dokumente: {bilanz.dokumente}, erzeugt: {bilanz.erzeugt}, "
        f"übersprungen: {bilanz.uebersprungen}, Fehler: {bilanz.fehler}"
    )


@app.command()
@cli_fehler
def analyse(
    ctx: typer.Context,
    art: str = typer.Option(
        "alle", "--art", "-a", help="zusammenfassung, klassifikation, bildbeschreibung oder alle."
    ),
    dokument: Optional[int] = typer.Option(None, "--dokument", "-d", help="Nur dieses Dokument (ID)."),
) -> None:
    """Analysiert Dokumente mit dem LLM: Zusammenfassung, Kategorie, Bildbeschreibung."""
    from app.enums import AnalyseArt

    s: Settings = ctx.obj
    if art not in ANALYSE_ARTEN:
        fehlerkonsole.print(f"[red]Unbekannte Art – erlaubt: {', '.join(ANALYSE_ARTEN)}[/red]")
        raise typer.Exit(2)
    arten = set(AnalyseArt) if art == "alle" else {AnalyseArt(art)}
    with session_aus(s) as session:
        bilanz = _analyse_stufe(session, s, arten, dokument)
    konsole.print(_analyse_zeile(bilanz))
    if bilanz.fehler:
        konsole.print("[yellow]Mindestens eine Analyse ist fehlgeschlagen – Details in den Läufen (Dokument-Seite).[/yellow]")


@app.command()
@cli_fehler
def pipeline(
    ctx: typer.Context,
    pfad: str = typer.Argument(..., help="Ordner (oder Datei) mit Rechercheunterlagen."),
) -> None:
    """Alles in einem Zug: einlesen, Entitäten erkennen (GliNER + Muster), Embeddings, Analysen."""
    from pathlib import Path

    from app.embed.index import embed_ausfuehren
    from app.enums import AnalyseArt, NerMethode
    from app.ingest.ablauf import ingest_clients, ingest_ordner
    from app.ner.ablauf import ner_ausfuehren
    from app.providers.factory import embedding_client

    s: Settings = ctx.obj
    ziel = Path(pfad)
    if not ziel.exists():
        fehlerkonsole.print(f"[red]Pfad nicht gefunden: {escape(pfad)}[/red]")
        raise typer.Exit(1)
    # Jede Stufe committet selbst - ein Fehler in einer spaeteren Stufe macht frueheres nicht rueckgaengig.
    stufe, nachher = "1/4 (Einlesen)", "`vfm ingest`, `vfm ner`, `vfm embed` und `vfm analyse`"
    try:
        with session_aus(s) as session:
            konsole.print("[bold]1/4 Einlesen[/bold]")
            i = ingest_ordner(session, ziel, s, ingest_clients(s))
            konsole.print(f"neu: {i.neu}, bekannt: {i.bekannt}, Fehler: {i.fehler}")

            stufe, nachher = "2/4 (Entitäten)", "`vfm ner`, `vfm embed` und `vfm analyse`"
            konsole.print("[bold]2/4 Entitäten (GliNER + Muster)[/bold]")
            n = ner_ausfuehren(session, s, {NerMethode.GLINER, NerMethode.MUSTER})
            konsole.print(
                f"Dokumente: {n.dokumente}, Entitäten: {n.entitaeten}, übersprungen: {n.uebersprungen}, Fehler: {n.fehler}"
            )

            stufe, nachher = "3/4 (Embeddings)", "`vfm embed` und `vfm analyse`"
            konsole.print("[bold]3/4 Embeddings[/bold]")
            e = embed_ausfuehren(session, embedding_client(s), provider=s.provider)
            konsole.print(f"Embeddings: {e.neu} neu, {e.vorhanden} bereits vorhanden")

            stufe, nachher = "4/4 (Analysen)", "`vfm analyse`"
            konsole.print("[bold]4/4 Analysen[/bold]")
            a = _analyse_stufe(session, s, set(AnalyseArt))
            konsole.print(_analyse_zeile(a))
    except ProviderFehler as fehler:
        fehlerkonsole.print(
            f"[red]Stufe {escape(stufe)} abgebrochen: {escape(str(fehler))} – "
            f"nach Behebung {escape(nachher)} ausführen.[/red]",
            highlight=False,
        )
        raise typer.Exit(2)
