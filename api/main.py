"""
F1 Data Platform — API entrypoint.

Replaces app.py from the old Flask app.
Visit http://localhost:8000/docs for interactive API docs (auto-generated).
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI

from db import pool, ro_pool
from routes import standings, races, query


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Open both DB pools at startup, close at shutdown
    pool.open()
    pool.wait()
    ro_pool.open()
    ro_pool.wait()
    yield
    pool.close()
    ro_pool.close()


app = FastAPI(
    title="F1 Data Platform API",
    description="Formula 1 race data, standings, and natural-language query interface.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
def health():
    """Liveness probe — used by external monitoring (webster / Cloudflare)."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
    return {"status": "ok"}


# Register route modules
app.include_router(standings.router)
app.include_router(races.router)
app.include_router(query.router)
