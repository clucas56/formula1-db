"""
Ingestion scheduler — replaces the host cron job from the old setup.

The old setup ran:
    crontab: 0 6 * * 1   /path/to/incremental_load.py

The new setup runs this scheduler.py forever in a container. It reads the
schedule from the INGESTION_CRON env var (default Monday 6am), sleeps until
the next scheduled time, runs the load, and repeats.

Why not APScheduler? For a single job on a fixed schedule, this is ~30 lines
and has no surprises. APScheduler is great when you have many jobs.
"""
import os
import sys
import time
import logging
from datetime import datetime
from croniter import croniter

# Add this dir to path so we can import the original scripts unchanged
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from incremental_load import main as run_incremental_load

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | scheduler | %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("scheduler")


def main():
    cron_expr = os.getenv("INGESTION_CRON", "0 6 * * 1")
    log.info(f"Scheduler starting. Cron expression: {cron_expr!r}")

    # Optionally run once at startup (useful for first deploy / manual triggers)
    if os.getenv("RUN_ON_START", "false").lower() == "true":
        log.info("RUN_ON_START=true — running incremental load immediately")
        try:
            run_incremental_load()
        except SystemExit:
            # incremental_load.main() calls sys.exit(1) on failure — catch
            # so the scheduler stays alive
            log.error("Incremental load exited with error; continuing scheduler")
        except Exception:
            log.exception("Incremental load raised; continuing scheduler")

    while True:
        cron = croniter(cron_expr, datetime.now())
        next_run = cron.get_next(datetime)
        sleep_seconds = (next_run - datetime.now()).total_seconds()

        log.info(f"Next run: {next_run.isoformat()} (in {int(sleep_seconds)}s)")
        time.sleep(max(sleep_seconds, 1))

        log.info("Running incremental load...")
        try:
            run_incremental_load()
            log.info("Incremental load complete")
        except SystemExit:
            log.error("Incremental load exited with error; continuing scheduler")
        except Exception:
            log.exception("Incremental load raised; continuing scheduler")


if __name__ == "__main__":
    main()
