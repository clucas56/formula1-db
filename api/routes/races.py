"""
/races — race-related endpoints.
"""
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from db import get_conn

router = APIRouter(prefix="/races", tags=["races"])


@router.get("/last")
def get_last_race():
    """
    Most recent race results — backs the homepage's `last_race_results` query.
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM last_race_results;")
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No recent race found")

    return rows


@router.get("/{season}/{round_num}")
def get_race(season: int, round_num: int):
    """Race details + results for a specific season/round."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT r.race_id, r.race_name, r.date, r.season_year, r.round,
                       c.name AS circuit_name, c.country
                FROM races r
                JOIN circuits c ON c.circuit_id = r.circuit_id
                WHERE r.season_year = %s AND r.round = %s
                """,
                (season, round_num),
            )
            race = cur.fetchone()

            if not race:
                raise HTTPException(status_code=404, detail="Race not found")

            cur.execute(
                """
                SELECT rr.finish_position, rr.grid_position, rr.points, rr.status,
                       d.first_name || ' ' || d.last_name AS driver_name,
                       con.name AS constructor_name
                FROM race_results rr
                JOIN drivers d      ON d.driver_id = rr.driver_id
                JOIN constructors con ON con.constructor_id = rr.constructor_id
                WHERE rr.race_id = %s
                ORDER BY rr.finish_position NULLS LAST
                """,
                (race["race_id"],),
            )
            results = cur.fetchall()

    return {"race": race, "results": results}
