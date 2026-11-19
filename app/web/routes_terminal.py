"""Browser-Terminal: leitet auf ttyd im App-Container weiter (eigener Port, siehe entrypoint.sh)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.web.vorlagen import templates

router = APIRouter()


@router.get("/terminal", response_class=HTMLResponse)
def terminal(request: Request, s: Settings = Depends(get_settings)):
    if not s.terminal_aktiv():
        return templates.TemplateResponse(request, "terminal_aus.html", {})
    host = request.url.hostname or "localhost"
    if ":" in host:  # IPv6-Literal
        host = f"[{host}]"
    return RedirectResponse(f"{request.url.scheme}://{host}:{s.terminal_port}/", status_code=302)
