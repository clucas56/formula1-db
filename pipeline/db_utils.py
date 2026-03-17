import psycopg2
import os
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load .env relative to this file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Log directories
LOG_BASE = Path(__file__).parent.parent / 'logs'

def setup_logging(script_name):
    """
    Set up logging to both file and console.
    Logs are separated by script into subfolders.
    """
    # Determine subfolder based on script name
    if script_name == "fetch_data":
        log_dir = LOG_BASE / "fetch"
    elif script_name == "incremental_load":
        log_dir = LOG_BASE / "incremental"
    else:
        log_dir = LOG_BASE / "other"

    # Create folder if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"{script_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

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
        password=os.getenv("DB_PASSWORD")
    )

def upsert(conn, table, data, conflict_column):
    """
    Insert a record, update if it already exists.
    Prevents duplicate data on re-runs.
    """
    if not data:
        return

    columns = list(data.keys())
    values = list(data.values())

    col_str = ", ".join(columns)
    val_placeholders = ", ".join(["%s"] * len(values))
    update_str = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != conflict_column])

    sql = f"""
        INSERT INTO {table} ({col_str})
        VALUES ({val_p
