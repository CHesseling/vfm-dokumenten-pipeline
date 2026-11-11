from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import Engine

from app.config import Settings, get_settings
from app.sql.abfrage import SqlFehler, lese_engine, sql_ausfuehren, zelle_text
from app.sql.beispiele import BEISPIELE
from app.web.vorlagen import templates

router = APIRouter()

LIMIT = 500


def get_sql_engine(s: Settings = Depends(get_settings)) -> Engine:
    return lese_engine(s)


def _seite(request: Request, sql: str, ergebnis=None, fehler: str | None = None):
    zeilen = (
        [[zelle_text(w) for w in z] for z in ergebnis.zeilen] if ergebnis is not None else None
    )
    return templates.TemplateResponse(
        request,
        "sql.html",
        {
            "sql": sql,
            "ergebnis": ergebnis,
            "zeilen": zeilen,
            "fehler": fehler,
            "beispiele": BEISPIELE,
            "limit": LIMIT,
        },
    )


@router.get("/sql")
def sql_formular(request: Request):
    return _seite(request, "")


@router.post("/sql")
def sql_abfragen(
    request: Request, sql: str = Form(""), engine: Engine = Depends(get_sql_engine)
):
    try:
        ergebnis = sql_ausfuehren(engine, sql, limit=LIMIT)
    except SqlFehler as fehler:
        return _seite(request, sql, fehler=str(fehler))
    return _seite(request, sql, ergebnis)
