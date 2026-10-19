from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app.api.v1 import (
    auth,
    baskets,
    catalog,
    deals,
    households,
    listings,
    lists,
    offers,
    plans,
    prices,
    sources,
    watch,
)
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.security import verify_csrf
from app.sources.fetcher import setup_fetcher_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Price fetcher for Amazon/Flipkart custom listings; only when DEALSCOUR_FETCHERS=1 (ADR-004).
    stop = setup_fetcher_loop(app, get_settings(), get_engine())
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="DealScour", version="0.1.0", lifespan=lifespan)
# Every router gets the CSRF check (X-DealScour: 1 on POST/PATCH/PUT/DELETE). Data routers also need a session
# through current_household_id; tests/test_auth_coverage.py walks every route to prove nothing is left open.
_csrf = [Depends(verify_csrf)]
for _router in (
    auth.router,
    households.router,
    deals.router,
    plans.router,
    lists.router,
    offers.router,
    baskets.router,
    prices.router,
    listings.router,
    sources.router,
    watch.router,
    catalog.router,
):
    app.include_router(_router, prefix="/api/v1", dependencies=_csrf)


@app.exception_handler(IntegrityError)
async def integrity_conflict(request: Request, exc: IntegrityError) -> JSONResponse:
    # Unique constraints are pre-checked per endpoint; this covers the race where two requests pass the check.
    return JSONResponse(status_code=409, content={"detail": "Conflicts with an existing record"})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _mount_web(static_dir: Path) -> None:
    """Serve the built web app; unknown non-API paths fall back to index.html (client-side routing)."""
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    def spa(path: str) -> FileResponse | JSONResponse:
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")


_static = get_settings().static_dir
if _static is not None and (_static / "index.html").is_file():
    _mount_web(_static)
