from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app.api.v1 import deals, lists, offers, plans
from app.core.config import get_settings

app = FastAPI(title="DealScour", version="0.1.0")
app.include_router(deals.router, prefix="/api/v1")
app.include_router(plans.router, prefix="/api/v1")
app.include_router(lists.router, prefix="/api/v1")
app.include_router(offers.router, prefix="/api/v1")


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
