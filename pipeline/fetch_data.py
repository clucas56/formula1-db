"""
Date: 3/17/2025 9:22 PM
Last reviewed by Chuck
"""

import requests
import time
import sys
from pathlib import Path
from db_utils import get_connection, upsert, setup_logging

#============================
# 1. Config
#============================

# Setup logging
logger = setup_logging("fetch_data")

# API base URL
BASE_URL = "https://api.jolpi.ca/ergast/f1"

# Rate limiting — 200 requests per hour max
# 0.5 seconds between requests = safe buffer
RATE_LIMIT_DELAY = 0.5 #Standard Delay
RESULTS_RATE_LIMIT_DELAY = 20   # longer delay for bulk season loads

#============================
# 2. API Fetch Function
#============================

def fetch(endpoint, params=None):
    
    #Make a GET request to the Jolpica API.
    #Handles errors and rate limiting automatically.

    url = f"{BASE_URL}/{endpoint}"
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()  # raises error if status code is 4xx or 5xx
        time.sleep(RATE_LIMIT_DELAY) # wait before next request
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
 
#============================
# 3. Fetch All Pages Function
#============================   
 
def fetch_all(endpoint):
    #Jolpica API returns max 100 records per call.
    #This function keeps fetching until it has ALL records.
    all_results = []
    offset = 0
    limit = 100

    while True:
        logger.info(f"Fetching {endpoint} offset={offset}")
        data = fetch(endpoint, params={"limit": limit, "offset": offset})

        if not data:
            break

        # Navigate to the actual data inside the JSON response
        mr_data = data.get("MRData", {})
        total = int(mr_data.get("total", 0))

        all_results.append(data)

        offset += limit
        if offset >= total:
            break

    return all_results


#============================
# 4. Load Circuits
#============================

def load_circuits(conn):
    #Fetch all F1 circuits and insert into database.
    logger.info("Loading circuits...")
    count = 0

    pages = fetch_all("circuits.json")

    for page in pages:
        circuits = page["MRData"]["CircuitTable"]["Circuits"]

        for c in circuits:
            upsert(conn, "circuits", {
                "circuit_id": c["circuitId"],
                "name":       c["circuitName"],
                "location":   c["Location"]["locality"],
                "country":    c["Location"]["country"],
                "lat":        c["Location"]["lat"],
                "lng":        c["Location"]["long"]
            }, "circuit_id")
            count += 1

    conn.commit()
    logger.info(f"Loaded {count} circuits")
    
#============================
# 5. Load Drivers
#============================

def load_drivers(conn):
    #Fetch all F1 drivers and insert into database.
    logger.info("Loading drivers...")
    count = 0

    pages = fetch_all("drivers.json")

    for page in pages:
        drivers = page["MRData"]["DriverTable"]["Drivers"]

        for d in drivers:
            upsert(conn, "drivers", {
                "driver_id":        d["driverId"],
                "code":             d.get("code"),
                "first_name":       d.get("givenName"),
                "last_name":        d.get("familyName"),
                "nationality":      d.get("nationality"),
                "date_of_birth":    d.get("dateOfBirth"),
                "permanent_number": d.get("permanentNumber")
            }, "driver_id")
            count += 1

    conn.commit()
    logger.info(f"Loaded {count} drivers")
    
#============================
# 6. Load Constructors
#============================

def load_constructors(conn):
    #Fetch all F1 constructors and insert into database.
    logger.info("Loading constructors...")
    count = 0

    pages = fetch_all("constructors.json")

    for page in pages:
        constructors = page["MRData"]["ConstructorTable"]["Constructors"]

        for c in constructors:
            upsert(conn, "constructors", {
                "constructor_id": c["constructorId"],
                "name":           c["name"],
                "nationality":    c["nationality"]
            }, "constructor_id")
            count += 1

    conn.commit()
    logger.info(f"Loaded {count} constructors")

#============================
# 7. Load Seasons and Races
#============================

def load_seasons(conn):
    #Fetch all seasons and their races.
    logger.info("Loading seasons and races...")
    season_count = 0
    race_count = 0

    # F1 started in 1950
    start_year = 1950
    end_year = 2025

    for year in range(start_year, end_year + 1):
        logger.info(f"Fetching season {year}...")

        pages = fetch_all(f"{year}/races.json")

        if not pages:
            continue

        races = pages[0]["MRData"]["RaceTable"]["Races"]
        total_rounds = len(races)

        # Insert season
        upsert(conn, "seasons", {
            "season_year":   year,
            "total_rounds":  total_rounds
        }, "season_year")
        season_count += 1

        # Insert each race
        for r in races:
            upsert(conn, "races", {
                "season_year": year,
                "round":       int(r["round"]),
                "race_name":   r["raceName"],
                "circuit_id":  r["Circuit"]["circuitId"],
                "date":        r.get("date"),
                "time":        r.get("time")
            }, "season_year, round")
            race_count += 1

        conn.commit()

    logger.info(f"Loaded {season_count} seasons and {race_count} races")
    time.sleep(RESULTS_RATE_LIMIT_DELAY) #Delay prior to moving to race results
#============================
# 9. Load Race Results
#============================

def load_race_results(conn):
    #Fetch all race results for every season.
    logger.info("Loading race results...")
    count = 0

    for year in range(1950, 2026):
        logger.info(f"Fetching race results for {year}...")

        pages = fetch_all(f"{year}/results.json")

        for page in pages:
            races = page["MRData"]["RaceTable"]["Races"]

            for race in races:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT race_id FROM races WHERE season_year = %s AND round = %s",
                    (year, int(race["round"]))
                )
                result = cursor.fetchone()
                cursor.close()

                if not result:
                    continue

                race_id = result[0]

                for r in race["Results"]:
                    upsert(conn, "race_results", {
                        "race_id":         race_id,
                        "driver_id":       r["Driver"]["driverId"],
                        "constructor_id":  r["Constructor"]["constructorId"],
                        "grid_position":   r.get("grid"),
                        "finish_position": r.get("position"),
                        "points":          r.get("points"),
                        "laps_completed":  r.get("laps"),
                        "status":          r["status"],
                        "fastest_lap":     r.get("FastestLap", {}).get("rank") == "1"
                    }, "race_id, driver_id")
                    count += 1

        conn.commit()
        logger.info(f"Season {year} complete - {count} total results so far")

        # Pause between seasons to avoid rate limiting
        logger.info(f"Waiting {RESULTS_RATE_LIMIT_DELAY} seconds before next season...")
        time.sleep(RESULTS_RATE_LIMIT_DELAY)

    logger.info(f"Loaded {count} race results")


#============================
# 10. Load Qualifying Results
#============================
def load_qualifying(conn):
    """Fetch all qualifying results for every season."""
    logger.info("Loading qualifying results...")
    count = 0

    for year in range(1950, 2026):
        logger.info(f"Fetching qualifying for {year}...")

        pages = fetch_all(f"{year}/qualifying.json")

        for page in pages:
            races = page["MRData"]["RaceTable"]["Races"]

            for race in races:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT race_id FROM races WHERE season_year = %s AND round = %s",
                    (year, int(race["round"]))
                )
                result = cursor.fetchone()
                cursor.close()

                if not result:
                    continue

                race_id = result[0]

                for q in race.get("QualifyingResults", []):
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
        logger.info(f"Season {year} qualifying complete - {count} total so far")
        time.sleep(RESULTS_RATE_LIMIT_DELAY)

    logger.info(f"Loaded {count} qualifying results")

#============================
# 11. Load Sprint Results
#============================
def load_sprint(conn):
    """Fetch all sprint results for every season."""
    logger.info("Loading sprint results...")
    count = 0

    # Sprints started in 2021
    for year in range(2021, 2026):
        logger.info(f"Fetching sprint results for {year}...")

        pages = fetch_all(f"{year}/sprint.json")

        for page in pages:
            races = page["MRData"]["RaceTable"]["Races"]

            for race in races:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT race_id FROM races WHERE season_year = %s AND round = %s",
                    (year, int(race["round"]))
                )
                result = cursor.fetchone()
                cursor.close()

                if not result:
                    continue

                race_id = result[0]

                for s in race.get("SprintResults", []):
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
        logger.info(f"Season {year} sprint complete - {count} total so far")
        time.sleep(RESULTS_RATE_LIMIT_DELAY)

    logger.info(f"Loaded {count} sprint results")

#============================
# 12. Load Driver Standings
#============================
def load_driver_standings(conn):
    """Fetch driver championship standings for every season."""
    logger.info("Loading driver standings...")
    count = 0

    for year in range(1950, 2026):
        logger.info(f"Fetching driver standings for {year}...")

        pages = fetch_all(f"{year}/driverStandings.json")

        for page in pages:
            standings_table = page["MRData"]["StandingsTable"]["StandingsLists"]

            for standing_list in standings_table:
                round_num = standing_list.get("round", 0)

                for s in standing_list.get("DriverStandings", []):
                    upsert(conn, "driver_standings", {
                        "season_year": year,
                        "round":       round_num,
                        "driver_id":   s["Driver"]["driverId"],
                        "points":      s.get("points"),
                        "position":    s.get("position"),
                        "wins":        s.get("wins")
                    }, "season_year, round, driver_id")
                    count += 1

        conn.commit()
        logger.info(f"Season {year} driver standings complete - {count} total so far")
        time.sleep(RESULTS_RATE_LIMIT_DELAY)

    logger.info(f"Loaded {count} driver standings")

#============================
# 13. Load Constructor Standings
#============================
def load_constructor_standings(conn):
    """Fetch constructor championship standings for every season."""
    logger.info("Loading constructor standings...")
    count = 0

    # Constructor championship started in 1958
    for year in range(1958, 2026):
        logger.info(f"Fetching constructor standings for {year}...")

        pages = fetch_all(f"{year}/constructorStandings.json")

        for page in pages:
            standings_table = page["MRData"]["StandingsTable"]["StandingsLists"]

            for standing_list in standings_table:
                round_num = standing_list.get("round", 0)

                for s in standing_list.get("ConstructorStandings", []):
                    upsert(conn, "constructor_standings", {
                        "season_year":    year,
                        "round":          round_num,
                        "constructor_id": s["Constructor"]["constructorId"],
                        "points":         s.get("points"),
                        "position":       s.get("position"),
                        "wins":           s.get("wins")
                    }, "season_year, round, constructor_id")
                    count += 1

        conn.commit()
        logger.info(f"Season {year} constructor standings complete - {count} total so far")
        time.sleep(RESULTS_RATE_LIMIT_DELAY)

    logger.info(f"Loaded {count} constructor standings")

#============================
# 14. Load Pit Stops
#============================
def load_pit_stops(conn):
    """Fetch pit stop data for every season."""
    logger.info("Loading pit stops...")
    count = 0

    # Pit stop data available from 2012 onwards
    for year in range(2012, 2026):
        logger.info(f"Fetching pit stops for {year}...")

        pages = fetch_all(f"{year}/pitstops.json")

        for page in pages:
            races = page["MRData"]["RaceTable"]["Races"]

            for race in races:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT race_id FROM races WHERE season_year = %s AND round = %s",
                    (year, int(race["round"]))
                )
                result = cursor.fetchone()
                cursor.close()

                if not result:
                    continue

                race_id = result[0]

                for p in race.get("PitStops", []):
                    upsert(conn, "pit_stops", {
                        "race_id":     race_id,
                        "driver_id":   p["driverId"],
                        "stop_number": p.get("stop"),
                        "lap":         p.get("lap"),
                        "duration":    p.get("duration")
                    }, "pit_id")
                    count += 1

        conn.commit()
        logger.info(f"Season {year} pit stops complete - {count} total so far")
        time.sleep(RESULTS_RATE_LIMIT_DELAY)

    logger.info(f"Loaded {count} pit stops")

#============================
# 15. MAIN
#============================
def main():
    """Run the full historical data load."""
    logger.info("Starting F1 full historical data load")
    logger.info("This will take a while due to API rate limiting...")

    conn = None

    try:
        conn = get_connection()
        logger.info("Database connected")

        # Load in order - dependencies first!
        load_circuits(conn)
        load_drivers(conn)
        load_constructors(conn)
        load_seasons(conn)
        load_race_results(conn)
        load_qualifying(conn)
        load_sprint(conn)
        load_driver_standings(conn)
        load_constructor_standings(conn)
        load_pit_stops(conn)

        logger.info("Full historical load complete!")

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
