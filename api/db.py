"""
Database connection pools for the API.

Two pools:
  - `pool`    — read/write, used by normal endpoints (standings, races, health)
  - `ro_pool` — read-only, used ONLY by the /query text-to-SQL endpoint

The read-only pool connects as a Postgres role that only has SELECT. This is
the PRIMARY safeguard for the text-to-SQL endpoint — the regex check in
routes/query.py is just defense-in-depth on top of it.

Until the read-only role is created (HANDOFF Phase 6), DB_RO_USER /
DB_RO_PASSWORD in .env can point at the same creds as DB_USER — but create
the real read-only role before exposing /query publicly.

Uses psycopg 3 (not psycopg2). Same author, modernized API, native pooling.
"""
import os
from contextlib import contextmanager
from psycopg_pool import ConnectionPool


def _conn_str(user: str, password: str) -> str:
    return (
        f"host={os.getenv('DB_HOST', 'postgres')} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"dbname={os.getenv('DB_NAME')} "
        f"user={user} "
        f"password={password}"
    )


# Read/write pool — normal endpoints
pool = ConnectionPool(
    _conn_str(os.getenv("DB_USER"), os.getenv("DB_PASSWORD")),
    min_size=2,
    max_size=10,
    open=False,
)

# Read-only pool — /query endpoint only
ro_pool = ConnectionPool(
    _conn_str(
        os.getenv("DB_RO_USER", os.getenv("DB_USER")),
        os.getenv("DB_RO_PASSWORD", os.getenv("DB_PASSWORD")),
    ),
    min_size=1,
    max_size=5,
    open=False,
)


@contextmanager
def get_conn():
    """Read/write connection from the main pool. For normal endpoints."""
    with pool.connection() as conn:
        yield conn


@contextmanager
def get_ro_conn():
    """Read-only connection. For the /query text-to-SQL endpoint only."""
    with ro_pool.connection() as conn:
        yield conn
