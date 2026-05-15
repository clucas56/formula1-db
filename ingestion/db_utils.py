"""
Shared utilities for the ingestion pipeline.

Mostly unchanged from the original db_utils.py. The only real change is that
get_connection() now reads env vars set by docker-compose instead of loading
a .env file (you can still drop a .env in the dir and python-dotenv will pick
it up — useful for local dev outside Docker).
"""
import os
import logging
from pathlib import Path
from datetime import datetime

import psycopg2
from dotenv import load_dotenv

# Load .env if present (for local dev). In Docker, env vars come from compose.
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

LOG_BASE = Path(__file__).parent / "logs"


def setup_logging(script_name):
    """Set up logging to both file and console, separated by script."""
    if script_name == "fetch_data":
        log_dir = LOG_BASE / "fetch"
    elif script_name == "incremental_load":
        log_dir = LOG_BASE / "incremental"
    else:
        log_dir = LOG_BASE / "other"

    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"{script_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # Don't reconfigure root logger if scheduler.py already did
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(),
            ],
        )
    else:
        # Add a file handler for this run
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        root.addHandler(fh)

    logger = logging.getLogger(script_name)
    logger.info(f"Logging initialized — {log_file}")
    return logger


def get_connection():
    """Create and return a database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def upsert(conn, table, data, conflict_column):
    """
    Insert a record, update if it already exists.
    `conflict_column` may be a single column or a comma-separated list
    (e.g. "race_id, driver_id") — matches the original interface.
    """
    if not data:
        return

    columns = list(data.keys())
    values = list(data.values())

    col_str = ", ".join(columns)
    val_placeholders = ", ".join(["%s"] * len(values))

    # Conflict columns may be composite — strip whitespace for the exclusion check
    conflict_cols = {c.strip() for c in conflict_column.split(",")}
    update_str = ", ".join(
        [f"{col} = EXCLUDED.{col}" for col in columns if col not in conflict_cols]
    )

    sql = (
        f"INSERT INTO {table} ({col_str}) "
        f"VALUES ({val_placeholders}) "
        f"ON CONFLICT ({conflict_column}) DO UPDATE SET {update_str}"
    )

    cursor = conn.cursor()
    cursor.execute(sql, values)
    cursor.close()
