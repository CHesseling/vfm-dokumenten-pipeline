"""Erklaerseite zur JSON-API (/api). Die Endpunkte kommen live aus dem OpenAPI-Schema,
damit die Seite nicht veraltet; Beispiele und Erklaertexte stehen hier."""

import json
import shlex

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.config import Settings, get_settings
from app.web.vorlagen import templates

router = APIRouter()

# Beispielwerte fuer curl; Pfade/Parameter ohne Eintrag bekommen einen Platzhalter.
BEISPIEL_PARAMETER = {
    "q": "Rechnung",
    "modus": "volltext",
    "top_k": 3,
    "label": "iban",
    "dokument_id": 1,
}
BEISPIEL_KOERPER = {
    "/api/frage": {"frage": "Wie hoch ist der Vertragswert?"},
}

FEHLERCODES = [
    ("401", "API-Token fehlt oder ist falsch (nur wenn API_TOKEN gesetzt ist)."),
    ("404", "Dokument mit dieser ID gibt es nicht."),
    ("409", "Noch keine Embeddings für das aktuelle Modell: erst vfm embed ausführen."),
    ("422", "Parameter fehlt oder hat den falschen Typ (Details stehen in der Antwort)."),
    ("502", "Ein Modell (Chat, Embedding, Rerank) ist nicht erreichbar."),
]


def _aufloesen(schema: dict, komponenten: dict) -> dict:
    """Eine Ebene $ref aufloesen (auch in anyOf mit null, wie bei `int | None`)."""
    if "$ref" in schema:
        return komponenten.get(schema["$ref"].rsplit("/", 1)[-1], {})
    for variante in schema.get("anyOf", []):
        if variante.get("type") != "null":
            return _aufloesen(variante, komponenten)
    return schema


def _typ(schema: dict, komponenten: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "enum" in schema:
        return " | ".join(str(w) for w in schema["enum"])
    if "anyOf" in schema:
        return " oder ".join(_typ(v, komponenten) for v in schema["anyOf"])
    if schema.get("type") == "array":
        return f"Liste von {_typ(schema.get('items', {}), komponenten)}"
    return schema.get("type", "–")


def _felder(schema: dict, komponenten: dict) -> tuple[str, list[dict]]:
    """(Beschreibung der Form, Felder) fuer ein Antwort- oder Anfrage-Schema."""
    form = "Objekt"
    if schema.get("type") == "array":
        form = "Liste von Objekten"
        schema = schema.get("items", {})
    schema = _aufloesen(schema, komponenten)
    pflicht = set(schema.get("required", []))
    felder = [
        {
            "name": name,
            "typ": _typ(feld, komponenten),
            "pflicht": name in pflicht,
            "beschreibung": feld.get("description", ""),
        }
        for name, feld in schema.get("properties", {}).items()
    ]
    return form, felder


def _curl(methode: str, pfad: str, parameter: list[dict], basis: str, token: bool) -> str:
    koerper = BEISPIEL_KOERPER.get(pfad)
    for p in parameter:
        if p["ort"] == "path":
            pfad = pfad.replace("{" + p["name"] + "}", str(BEISPIEL_PARAMETER.get(p["name"], 1)))
    abfrage = [
        f"{p['name']}={BEISPIEL_PARAMETER[p['name']]}"
        for p in parameter
        if p["ort"] == "query" and p["name"] in BEISPIEL_PARAMETER
    ]
    url = basis + pfad + ("?" + "&".join(abfrage) if abfrage else "")
    teile = ["curl"]
    if methode != "GET":
        teile += ["-X", methode]
    if token:
        teile += ["-H", shlex.quote("Authorization: Bearer DEIN_TOKEN")]
    if koerper is not None:
        teile += ["-H", shlex.quote("Content-Type: application/json"),
                  "-d", shlex.quote(json.dumps(koerper, ensure_ascii=False))]
    teile.append(shlex.quote(url))
    return " ".join(teile)


def endpunkte(openapi: dict, basis: str, token: bool) -> list[dict]:
    komponenten = openapi.get("components", {}).get("schemas", {})
    ergebnis = []
    for pfad, methoden in openapi.get("paths", {}).items():
        if not pfad.startswith("/api/"):
            continue
        for methode, op in methoden.items():
            parameter = [
                {
                    "name": p["name"],
                    "ort": p["in"],
                    "pflicht": p.get("required", False),
                    "typ": _typ(p.get("schema", {}), komponenten),
                    "standard": p.get("schema", {}).get("default"),
                    "beschreibung": p.get("description", ""),
                }
                for p in op.get("parameters", [])
            ]
            koerper = None
            inhalt = op.get("requestBody", {}).get("content", {}).get("application/json")
            if inhalt:
                koerper = _felder(inhalt["schema"], komponenten)
            antwort = None
            ok = op.get("responses", {}).get("200", {}).get("content", {}).get("application/json")
            if ok:
                antwort = _felder(ok["schema"], komponenten)
            ergebnis.append(
                {
                    "methode": methode.upper(),
                    "pfad": pfad,
                    "titel": op.get("summary", ""),
                    "beschreibung": op.get("description", ""),
                    "parameter": parameter,
                    "koerper": koerper,
                    "antwort": antwort,
                    "curl": _curl(methode.upper(), pfad, parameter, basis, token),
                }
            )
    return ergebnis


@router.get("/api-hilfe", response_class=HTMLResponse)
def api_hilfe(request: Request, s: Settings = Depends(get_settings)):
    basis = str(request.base_url).rstrip("/")
    token = bool(s.api_token)
    return templates.TemplateResponse(
        request,
        "api_hilfe.html",
        {
            "basis": basis,
            "token": token,
            "endpunkte": endpunkte(request.app.openapi(), basis, token),
            "fehlercodes": FEHLERCODES,
        },
    )
