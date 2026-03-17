"""
Date: 3/16/2025 11:26 PM
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
RATE_LIMIT_DELAY = 0.5

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
    """Fetch all F1 circuits and insert into database."""
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
    """Fetch all F1 drivers and insert into database."""
    logger.info("Loading drivers...")
    count = 0

    pages = fetch_all("drivers.json")

    for page in pages:
        drivers = page["MRData"]["DriverTable"]["Drivers"]

        for d in drivers:
            upsert(conn, "drivers", {
                "driver_id":        d["driverId"],
                "code":             d.get("code"),
                "first_name":       d["givenName"],
                "last_name":        d["familyName"],
                "nationality":      d["nationality"],
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
    """Fetch all F1 constructors and insert into database."""
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
    """Fetch all seasons and their races."""
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
            }, "race_id")
            race_count += 1

        conn.commit()

    logger.info(f"Loaded {season_count} seasons and {race_count} races")

#============================
# 8. Load Race Results
#============================

def load_race_results(conn):
    """Fetch all race results for every season."""
    logger.info("Loading race results...")
    count = 0

    for year in range(1950, 2026):
        logger.info(f"Fetching race results for {year}...")

        pages = fetch_all(f"{year}/results.json")

        for page in pages:
            races = page["MRData"]["RaceTable"]["Races"]

            for race in races:
                # Get race_id from database
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
                        "race_id":          race_id,
                        "driver_id":        r["Driver"]["driverId"],
                        "constructor_id":   r["Constructor"]["constructorId"],
                        "grid_position":    r.get("grid"),
                        "finish_position":  r.get("position"),
                        "points":           r.get("points"),
                        "laps_completed":   r.get("laps"),
                        "status":           r["status"],
                        "fastest_lap":      r.get("FastestLap", {}).get("rank") == "1"
                    }, "result_id")
                    count += 1

        conn.commit()

    logger.info(f"Loaded {count} race results")

#============================
# 9. MAIN
#============================

def main():
    """Run the full historical data load."""
    logger.info("Starting F1 full historical data load")
    logger.info("This will take a while due to API rate limiting...")

    conn = None

    try:
        conn = get_connection()
        logger.info("Database connected")

        # Load in order — dependencies first!
        load_circuits(conn)
        load_drivers(conn)
        load_constructors(conn)
        load_seasons(conn)       # needs circuits to exist first
        load_race_results(conn)  # needs races, drivers, constructors

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
