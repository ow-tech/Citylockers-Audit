"""HTTP entry point for the central audit service."""

from fastapi import FastAPI

app = FastAPI(title="CityLockers Audit", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Return liveness only; storage health belongs to later readiness work."""
    return {"status": "healthy"}
