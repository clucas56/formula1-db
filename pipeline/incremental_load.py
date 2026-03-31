# =============================================================================
# incremental_load.py
# Loads the latest race weekend data after each race
# Run after each race weekend to keep database up to date
# =============================================================================

import requests
import time
import sys
from db_utils import get_connection, upsert, setup_logging

# =============================================================================
# CONFIGURATION
# =============================================================================

logger = setup_logging("incremental_load")

BASE_URL = "https://api.jolpi.ca/ergast/f1"
RATE_LIMIT_DELAY = 0.5

# =============================================================================
# API HELPERS
# =============================================================================

def fetch(endpoint, params=None):
    """Make a GET request to the Jolpica API."""
    url = f"{BASE_URL}/{endpoint}"

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        time.sleep(RATE_LIMIT_DELAY)
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching {url}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error fetching {url}: {e}")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error fetching {url}")
        return None

# =============================================================================
# GET LATEST RACE
# =============================================================================

def get_latest_race():
    """
    Ask the API for the most recently completed race.
    Returns season year and round number.
    """
    logger.info("Fetching latest completed race from API...")

    data = fetch("current/last/results.json")

    if not data:
        logger.error("Could not fetch latest race from API")
        return None, None

    races = data["MRData"]["RaceTable"]["Races"]

    if not races:
        logger.error("No races found in API response")
        return None, None

    latest = races[0]
    season = int(latest["season"])
    round_num = int(latest["round"])

    logger.info(f"Latest race: {latest['raceName']} - Season {season} Round {round_num}")
    return season, round_num

# =============================================================================
# CHECK IF ALREADY LOADED
# =============================================================================

def already_loaded(conn, season, round_num):
    """
    Check if we already have this race in the database.
    Prevents loading the same race twice.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT race_id FROM races WHERE season_year = %s AND round = %s",
        (season, round_num)
    )
    result = cursor.fetchone()
    cursor.close()

    if result:
        logger.info(f"Season {season} Round {round_num} already exists in database - checking for missing data")
        return result[0]
    
    logger.info(f"Season {season} Round {round_num} is new - loading...")
    return None

# =============================================================================
# LOAD RACE
# =============================================================================

def load_race(conn, season, round_num):
    """
    Load the race details into the races table.
    Also ensures the season exists in the seasons table.
    """
    logger.info(f"Loading race details for season {season} round {round_num}...")

    data = fetch(f"{season}/{round_num}/races.json")

    if not data:
        logger.error("Could not fetch race details")
        return None

    races = data["MRData"]["RaceTable"]["Races"]

    if not races:
        logger.error("No race data returned")
        return None

    r = races[0]

    # Make sure season exists first
    upsert(conn, "seasons", {
        "season_year":  season,
        "total_rounds": round_num
    }, "season_year")

    # Insert the race
    upsert(conn, "races", {
        "season_year": season,
        "round":       round_num,
        "race_name":   r["raceName"],
        "circuit_id":  r["Circuit"]["circuitId"],
        "date":        r.get("date"),
        "time":        r.get("time")
    }, "season_year, round")

    # Get the race_id back from the database
    cursor = conn.cursor()
    cursor.execute(
        "SELECT race_id FROM races WHERE season_year = %s AND round = %s",
        (season, round_num)
    )
    result = cursor.fetchone()
    cursor.close()

    conn.commit()
    logger.info(f"Race loaded successfully")
    return result[0] if result else None

# =============================================================================
# LOAD RACE RESULTS
# =============================================================================

def load_race_results(conn, season, round_num, race_id):
    """Load race results for the latest round."""
    logger.info(f"Loading race results for season {season} round {round_num}...")

    data = fetch(f"{season}/{round_num}/results.json")

    if not data:
        logger.error("Could not fetch race results")
        return

    races = data["MRData"]["RaceTable"]["Races"]

    if not races:
        logger.info("No race results available yet")
        return

    count = 0
    for r in races[0]["Results"]:
        # Make sure driver exists
        d = r["Driver"]
        upsert(conn, "drivers", {
            "driver_id":        d["driverId"],
            "code":             d.get("code"),
            "first_name":       d.get("givenName"),
            "last_name":        d.get("familyName"),
            "nationality":      d.get("nationality"),
            "date_of_birth":    d.get("dateOfBirth"),
            "permanent_number": d.get("permanentNumber")
        }, "driver_id")

        # Make sure constructor exists
        c = r["Constructor"]
        upsert(conn, "constructors", {
            "constructor_id": c["constructorId"],
            "name":           c["name"],
            "nationality":    c.get("nationality")
        }, "constructor_id")

        # Insert result
        upsert(conn, "race_results", {
            "race_id":         race_id,
            "driver_id":       d["driverId"],
            "constructor_id":  c["constructorId"],
            "grid_position":   r.get("grid"),
            "finish_position": r.get("position"),
            "points":          r.get("points"),
            "laps_completed":  r.get("laps"),
            "status":          r.get("status"),
            "fastest_lap":     r.get("FastestLap", {}).get("rank") == "1"
        }, "race_id, driver_id")
        count += 1

    conn.commit()
    logger.info(f"Loaded {count} race results")

# =============================================================================
# LOAD QUALIFYING
# =============================================================================

def load_qualifying(conn, season, round_num, race_id):
    """Load qualifying results for the latest round."""
    logger.info(f"Loading qualifying for season {season} round {round_num}...")

    data = fetch(f"{season}/{round_num}/qualifying.json")

    if not data:
        logger.error("Could not fetch qualifying results")
        return

    races = data["MRData"]["RaceTable"]["Races"]

    if not races:
        logger.info("No qualifying data available yet")
        return

    count = 0
    for q in races[0].get("QualifyingResults", []):
        upsert(conn, "qualifying_results", {
            "race_id":        race_id,
            "driver_id":      q["Driver"]["driverId"],
            "constructor_id": q["Constructor"]["constructorId"],
            "position":       q.get("position"),
            "q1_time":        q.get("Q1"),
            "q2_time":        q.get("Q2"),
            "q3_time":        q.get("Q3")
        }, "race_id, driver_id")
        count += 1

    conn.commit()
    logger.info(f"Loaded {count} qualifying results")


# =============================================================================
# LOAD SPRINT
# =============================================================================

def load_sprint(conn, season, round_num, race_id):
    """Load sprint results if this was a sprint weekend."""
    logger.info(f"Checking for sprint results for season {season} round {round_num}...")

    data = fetch(f"{season}/{round_num}/sprint.json")

    if not data:
        logger.info("No sprint data available")
        return

    races = data["MRData"]["RaceTable"]["Races"]

    if not races:
        logger.info("No sprint race this weekend")
        return

    count = 0
    for s in races[0].get("SprintResults", []):
        upsert(conn, "sprint_results", {
            "race_id":         race_id,
            "driver_id":       s["Driver"]["driverId"],
            "constructor_id":  s["Constructor"]["constructorId"],
            "grid_position":   s.get("grid"),
            "finish_position": s.get("position"),
            "points":          s.get("points"),
            "status":          s.get("status")
        }, "race_id, driver_id")
        count += 1

    conn.commit()
    if count > 0:
        logger.info(f"Loaded {count} sprint results")
    else:
        logger.info("No sprint results this weekend")

# =============================================================================
# LOAD STANDINGS
# =============================================================================

def load_standings(conn, season, round_num):
    """Load driver and constructor standings after the latest round."""
    logger.info(f"Loading standings for season {season} round {round_num}...")

    # Driver standings
    data = fetch(f"{season}/{round_num}/driverStandings.json")

    if data:
        standings_lists = data["MRData"]["StandingsTable"]["StandingsLists"]

        count = 0
        for standing_list in standings_lists:
            for s in standing_list.get("DriverStandings", []):
                upsert(conn, "driver_standings", {
                    "season_year": season,
                    "round":       round_num,
                    "driver_id":   s["Driver"]["driverId"],
                    "points":      s.get("points"),
                    "position":    s.get("position"),
                    "wins":        s.get("wins")
                }, "season_year, round, driver_id")
                count += 1

        conn.commit()
        logger.info(f"Loaded {count} driver standings")

    # Constructor standings
    data = fetch(f"{season}/{round_num}/constructorStandings.json")

    if data:
        standings_lists = data["MRData"]["StandingsTable"]["StandingsLists"]

        count = 0
        for standing_list in standings_lists:
            for s in standing_list.get("ConstructorStandings", []):
                upsert(conn, "constructor_standings", {
                    "season_year":    season,
                    "round":          round_num,
                    "constructor_id": s["Constructor"]["constructorId"],
                    "points":         s.get("points"),
                    "position":       s.get("position"),
                    "wins":           s.get("wins")
                }, "season_year, round, constructor_id")
                count += 1

        conn.commit()
        logger.info(f"Loaded {count} constructor standings")

# =============================================================================
# MAIN
# =============================================================================

def main():
    """Load the latest race weekend data."""
    logger.info("Starting incremental load...")

    conn = None

    try:
        conn = get_connection()
        logger.info("Database connected")

        # Step 1 - Find latest race from API
        season, round_num = get_latest_race()
        if not season:
            logger.error("Could not determine latest race - exiting")
            sys.exit(1)

        # Step 2 - Check if already loaded
        race_id = already_loaded(conn, season, round_num)

        # Step 3 - Load race if new or get existing race_id
        if not race_id:
            race_id = load_race(conn, season, round_num)

        if not race_id:
            logger.error("Could not load race - exiting")
            sys.exit(1)

        # Step 4 - Load all race weekend data
        load_race_results(conn, season, round_num, race_id)
        load_qualifying(conn, season, round_num, race_id)
        load_sprint(conn, season, round_num, race_id)
        load_standings(conn, season, round_num)

        logger.info(f"Incremental load complete for season {season} round {round_num}!")

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if conn:
            conn.rollback()
        sys.exit(1)

    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")

if __name__ == "__main__":
    main()
