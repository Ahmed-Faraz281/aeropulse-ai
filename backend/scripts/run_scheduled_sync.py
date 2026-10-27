"""
AeroPulse AI — Standalone Scheduled Continuous Monitoring Runner
Phase 18 / Production Automation CLI Runner

Can be invoked as a standalone CLI script, via Render Cron Job,
or via GitHub Actions / system cron:
    python backend/scripts/run_scheduled_sync.py
"""
import asyncio
import logging
import sys
import os

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.core.config import settings
from backend.app.core.database import SessionLocal, check_db_connection
from backend.app.services.automation_service import get_automation_supervisor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aeropulse.scheduled_sync")


async def main():
    logger.info("Initializing AeroPulse AI Scheduled Ingestion Runner...")

    # 1. Check DB connectivity
    health = check_db_connection()
    if not health.get("ok"):
        logger.error("Database connection failure: %s", health.get("error"))
        sys.exit(1)

    # 2. Get supervisor and run sync cycle
    supervisor = get_automation_supervisor()
    summary = await supervisor.run_sync_cycle(source="cron_job")

    logger.info(
        "Sync cycle completed: status=%s, stations=%d (failed=%d), obs=%d, preds=%d, duration=%.2fs",
        summary.status,
        summary.stations_processed,
        summary.stations_failed,
        summary.observations_ingested,
        summary.predictions_generated,
        summary.duration_seconds or 0.0,
    )

    if summary.status == "error":
        logger.error("Sync cycle failed with errors: %s", summary.errors)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
