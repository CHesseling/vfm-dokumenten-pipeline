from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.logging_config import configure_logging
from app.api import routes as api_routes
from app.web import routes_dokumente, routes_entitaeten, routes_sql, routes_status, routes_suche, routes_upload


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        level = get_settings().log_level
    except Exception:  # Settings nicht baubar (z. B. Tests ohne Env)
        level = "INFO"
    configure_logging(level)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="VFM-Pipeline", lifespan=lifespan)

    app.include_router(routes_dokumente.router)
    app.include_router(routes_upload.router)
    app.include_router(routes_sql.router)
    app.include_router(routes_entitaeten.router)
    app.include_router(routes_suche.router)
    app.include_router(routes_status.router)
    app.include_router(api_routes.router)

    @app.get("/gesundheit")
    def gesundheit() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
