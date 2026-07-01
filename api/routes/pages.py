from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from psycopg.rows import dict_row

from db import get_conn

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM current_standings ORDER BY position;")
            standings = cur.fetchall()

            cur.execute("SELECT * FROM last_race_results ORDER BY finish_position NULLS LAST;")
            last_race = cur.fetchall()

            cur.execute("""
                SELECT
                    cs.position,
                    c.name AS constructor_name,
                    cs.points,
                    cs.wins
                FROM constructor_standings cs
                JOIN constructors c ON c.constructor_id = cs.constructor_id
                WHERE cs.season_year = (SELECT MAX(season_year) FROM constructor_standings)
                  AND cs.round = (
                      SELECT MAX(round) FROM constructor_standings cs2
                      WHERE cs2.season_year = cs.season_year
                  )
                ORDER BY cs.position;
            """)
            constructor_standings = cur.fetchall()

            cur.execute("""
                SELECT race_id, season_year, round, race_name, date
                FROM races
                WHERE season_year = (SELECT MAX(season_year) FROM races)
                ORDER BY round;
            """)
            season_races = cur.fetchall()

    season_year = standings[0]['position'] and season_races[0]['season_year'] if season_races else ""

    return templates.TemplateResponse("index.html", {
        "request": request,
        "standings": standings,
        "last_race": last_race,
        "constructor_standings": constructor_standings,
        "season_races": season_races,
        "season_year": season_races[0]['season_year'] if season_races else "",
    })


@router.get("/race/{season}/{round_num}", response_class=HTMLResponse)
def race_detail(request: Request, season: int, round_num: int):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    rr.finish_position,
                    rr.grid_position,
                    rr.points,
                    rr.status,
                    d.first_name || ' ' || d.last_name AS driver_name,
                    c.name AS constructor_name,
                    r.race_name,
                    r.date,
                    r.season_year,
                    r.round
                FROM race_results rr
                JOIN races r        ON r.race_id = rr.race_id
                JOIN drivers d      ON d.driver_id = rr.driver_id
                JOIN constructors c ON c.constructor_id = rr.constructor_id
                WHERE r.season_year = %s AND r.round = %s
                ORDER BY rr.finish_position NULLS LAST;
            """, (season, round_num))
            results = cur.fetchall()

    if not results:
        raise HTTPException(status_code=404, detail="Race not found")

    return templates.TemplateResponse("race.html", {
        "request": request,
        "results": results,
    })


@router.get("/seasons", response_class=HTMLResponse)
def seasons_list(request: Request):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT season_year, total_rounds FROM seasons ORDER BY season_year DESC;")
            seasons = cur.fetchall()

    return templates.TemplateResponse("seasons.html", {
        "request": request,
        "seasons": seasons,
    })


@router.get("/seasons/{year}", response_class=HTMLResponse)
def season_detail(request: Request, year: int):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT round, race_name, date
                FROM races
                WHERE season_year = %s
                ORDER BY round;
            """, (year,))
            races = cur.fetchall()

    if not races:
        raise HTTPException(status_code=404, detail="Season not found")

    return templates.TemplateResponse("season_detail.html", {
        "request": request,
        "races": races,
        "year": year,
    })


@router.get("/drivers", response_class=HTMLResponse)
def drivers_list(request: Request):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT driver_id, first_name, last_name, nationality
                FROM drivers
                ORDER BY last_name, first_name;
            """)
            drivers = cur.fetchall()

    return templates.TemplateResponse("drivers.html", {
        "request": request,
        "drivers": drivers,
    })


@router.get("/drivers/{driver_id}", response_class=HTMLResponse)
def driver_detail(request: Request, driver_id: str):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT driver_id, first_name, last_name, nationality
                FROM drivers WHERE driver_id = %s;
            """, (driver_id,))
            driver = cur.fetchone()

            if not driver:
                raise HTTPException(status_code=404, detail="Driver not found")

            cur.execute("""
                SELECT
                    COUNT(*) AS races,
                    COUNT(*) FILTER (WHERE finish_position = 1) AS wins,
                    COALESCE(SUM(points), 0) AS total_points
                FROM race_results
                WHERE driver_id = %s;
            """, (driver_id,))
            stats = cur.fetchone()

            cur.execute("""
                SELECT DISTINCT r.season_year
                FROM race_results rr
                JOIN races r ON r.race_id = rr.race_id
                WHERE rr.driver_id = %s
                ORDER BY r.season_year DESC;
            """, (driver_id,))
            active_seasons = [row["season_year"] for row in cur.fetchall()]

    return templates.TemplateResponse("driver_detail.html", {
        "request": request,
        "driver": driver,
        "stats": stats,
        "active_seasons": active_seasons,
    })


@router.get("/circuits", response_class=HTMLResponse)
def circuits_list(request: Request):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT circuit_id, name, country, lat, lng
                FROM circuits
                ORDER BY country, name;
            """)
            circuits = cur.fetchall()

    return templates.TemplateResponse("circuits.html", {
        "request": request,
        "circuits": circuits,
    })
