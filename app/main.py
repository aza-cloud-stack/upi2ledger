"""FastAPI application entry point for upi2ledger."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, Request
from fastapi.applications import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, load_settings
from app.db.models import get_db_path, init_db
from app.logging import setup_logging
from app.routes.auth import router as auth_router
from app.routes.gmail import router as gmail_router
from app.routes.sync import router as sync_router
from app.routes.transactions import router as transactions_router
from app.security import AuthRequired, SecurityHeadersMiddleware, require_auth

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    # Load config
    settings = load_settings()
    app.state.settings = settings

    # Setup logging
    setup_logging(debug=settings.app.debug)
    logger.info("Starting upi2ledger")

    # Init database
    db_path = get_db_path()
    init_db(db_path)
    app.state.db_path = db_path

    yield

    logger.info("Shutting down upi2ledger")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional pre-loaded settings (for testing). If None, loaded in lifespan.
    """
    app = FastAPI(
        title="upi2ledger",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan if settings is None else None,
    )

    # If settings provided directly (testing), attach them now
    if settings is not None:
        app.state.settings = settings
        db_path = get_db_path()
        init_db(db_path)
        app.state.db_path = db_path

    # Security middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Static files
    static_dir = Path("static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory="static"), name="static")

    # Templates
    templates = Jinja2Templates(directory="templates", autoescape=True)

    # Auth exception handler — redirect unauthenticated requests to /login
    @app.exception_handler(AuthRequired)
    async def auth_required_handler(request: Request, exc: AuthRequired) -> RedirectResponse:
        return RedirectResponse(url="/login", status_code=303)

    # Routes
    app.include_router(auth_router)
    app.include_router(gmail_router)
    app.include_router(sync_router)
    app.include_router(transactions_router)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, username: str = Depends(require_auth)) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {"username": username})

    return app


if __name__ == "__main__":
    import uvicorn

    _settings = load_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=_settings.app.host,
        port=_settings.app.port,
        reload=_settings.app.debug,
    )
