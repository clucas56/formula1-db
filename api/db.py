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


pool = ConnectionPool(
    _conn_str(os.getenv("DB_USER"), os.getenv("DB_PASSWORD")),
    min_size=2,
    max_size=10,
    open=False,
)


@contextmanager
def get_conn():
    with pool.connection() as conn:
        yield conn
