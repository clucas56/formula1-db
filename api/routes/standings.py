"""
/standings — current driver standings.

Replaces the Flask query against `current_standings` view.
"""
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from db import get_conn
from models import DriverStanding

router = APIRouter(prefix="/standings", tags=["standings"])


@router.get("/drivers", response_model=list[DriverStanding])
def get_driver_standings():
    """
    Current driver standings (latest round of the current season).

    Reads from the `current_standings` view that you already have in the DB.
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM current_standings ORDER BY position;")
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No standings found")

    return rows
