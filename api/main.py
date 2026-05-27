from contextlib import asynccontextmanager
from fastapi import FastAPI

from db import pool
from routes import standings, races, pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    pool.wait()
    yield
    pool.close()


app = FastAPI(
    title="F1 Data Platform API",
    description="Formula 1 race data and standings.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
def health():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            cur.fetchone()
    return {"status": "ok"}


app.include_router(pages.router)
app.include_router(standings.router)
app.include_router(races.router)
