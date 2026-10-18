from fastapi import FastAPI

from app.api.v1 import deals, plans

app = FastAPI(title="DealScour", version="0.1.0")
app.include_router(deals.router, prefix="/api/v1")
app.include_router(plans.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
