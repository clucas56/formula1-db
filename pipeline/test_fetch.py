# =============================================================================
# test_fetch.py
# Quick test to verify API connection and database connection
# before running the full historical load
# =============================================================================

import sys
from db_utils import get_connection, upsert, setup_logging
import requests

# =============================================================================
# SETUP
# =============================================================================

logger = setup_logging("fetch_data")
BASE_URL = "https://api.jolpi.ca/ergast/f1"

# =============================================================================
# TEST API CONNECTION
# =============================================================================

def test_api():
    """Test that we can reach the Jolpica API."""
    logger.info("Testing API connection...")
    
    url = f"{BASE_URL}/circuits.json?limit=5"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        circuits = data["MRData"]["CircuitTable"]["Circuits"]
        total = data["MRData"]["total"]
        logger.info(f"API connection successful - total circuits available: {total}")
        logger.info(f"Sample circuit: {circuits[0]['circuitName']} - {circuits[0]['Location']['country']}")
        return True
    except Exception as e:
        logger.error(f"API connection failed: {e}")
        return False

# =============================================================================
# TEST DATABASE CONNECTION
# =============================================================================

def test_db():
    """Test that we can connect to PostgreSQL."""
    logger.info("Testing database connection...")
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM circuits")
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        logger.info(f"Database connection successful - circuits table has {count} records")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False

# =============================================================================
# TEST SMALL CIRCUIT LOAD
# =============================================================================

def test_load_circuits():
    """Load just 5 circuits as a test."""
    logger.info("Testing circuit load - fetching 5 circuits...")
    
    try:
        url = f"{BASE_URL}/circuits.json?limit=5"
        response = requests.get(url, timeout=10)
        data = response.json()
        circuits = data["MRData"]["CircuitTable"]["Circuits"]
        
        conn = get_connection()
        
        for c in circuits:
            upsert(conn, "circuits", {
                "circuit_id": c["circuitId"],
                "name":       c["circuitName"],
                "location":   c["Location"]["locality"],
                "country":    c["Location"]["country"],
                "lat":        c["Location"]["lat"],
                "lng":        c["Location"]["long"]
            }, "circuit_id")
            logger.info(f"Inserted: {c['circuitName']}")
        
        conn.commit()
        conn.close()
        logger.info("Test circuit load successful!")
        return True
    except Exception as e:
        logger.error(f"Test circuit load failed: {e}")
        return False

# =============================================================================
# MAIN
# =============================================================================

def main():
    logger.info("Starting test run...")
    
    api_ok = test_api()
    if not api_ok:
        logger.error("API test failed - check internet connection")
        sys.exit(1)
    
    db_ok = test_db()
    if not db_ok:
        logger.error("Database test failed - check SSH tunnel and credentials")
        sys.exit(1)
    
    load_ok = test_load_circuits()
    if not load_ok:
        logger.error("Circuit load test failed")
        sys.exit(1)
    
    logger.info("All tests passed - safe to run full historical load!")

if __name__ == "__main__":
    main()
